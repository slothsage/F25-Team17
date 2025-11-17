from datetime import date, datetime, time, timedelta
from django.utils import timezone
from io import BytesIO
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.conf import settings
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseBadRequest 
from django.db.models import Sum, Count, Q
from accounts.models import PointsLedger, DriverProfile
from accounts.services import get_driver_points_balance
from .models import PointsConfig
from .forms import PointsConfigForm, CheckoutForm, SponsorCatalogItemForm
from .models import Order, OrderItem, CartItem, Favorite, PointsConfig, SponsorCatalogItem, DriverCatalogItem, SavedCart, SavedCartItem
from django.urls import reverse
from .models import Wishlist, WishListItem
from django.core.paginator import Paginator
from .ebay_service import ebay_service
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import JsonResponse
from xhtml2pdf import pisa
import json
import csv
from accounts.models import SponsorPointsAccount


# A tiny editable set of eBay category IDs (Browse API uses numeric IDs)
EBAY_CATEGORY_CHOICES = [
    ("", "All Categories"),
    ("9355", "Cell Phones & Smartphones"),
    ("9359", "Cases, Covers & Skins"),
    ("15032", "Headphones"),
    ("58058", "Home Audio"),
    ("177", "Books"),
    ("293", "Music"),
]


try:
    from accounts.notifications import send_in_app_notification
except Exception:
    send_in_app_notification = None

@staff_member_required
def points_settings(request):
    cfg = PointsConfig.get_solo()
    if request.method == "POST":
        form = PointsConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()  # model.save() clears the cache in your model hook
            messages.success(request, "Points per USD updated.")
            return redirect("shop:points_settings")
    else:
        form = PointsConfigForm(instance=cfg)

    return render(request, "shop/points_settings.html", {"form": form})

@login_required
@transaction.atomic
def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, driver=request.user)

    if request.method != "POST":
        return redirect("shop:order_detail", order_id=order.id)

    # Check if order can be cancelled
    if not order.can_cancel():
        messages.error(request, f"Order #{order.id} cannot be cancelled. Only pending, confirmed, or processing orders can be cancelled.")
        return redirect("shop:order_detail", order_id=order.id)

    # Refund points to the wallets that were used for this order
    from accounts.models import SponsorPointsTransaction
    transactions = SponsorPointsTransaction.objects.filter(
        order=order,
        tx_type="debit"  # Only refund debit transactions (point deductions)
    ).select_related("wallet")

    refunded_total = 0
    for transaction in transactions:
        # Refund the points to the same wallet
        refund_amount = transaction.amount
        transaction.wallet.apply_points(
            refund_amount,
            reason=f"Refund for cancelled Order #{order.id}",
            created_by=request.user,
            order=None,  # Don't link refund transaction to the cancelled order
        )
        refunded_total += refund_amount

    # Update order status
    order.status = "cancelled"
    order.save(update_fields=["status", "updated_at"])

    # Send success message
    if refunded_total > 0:
        messages.success(
            request,
            f"Order #{order.id} has been cancelled. {refunded_total} points have been refunded to your account."
        )
    else:
        messages.success(request, f"Order #{order.id} has been cancelled.")

    # Send notification
    try:
        from accounts.notifications import send_in_app_notification
        from django.urls import reverse
        send_in_app_notification(
            request.user,
            "orders",
            "Order Cancelled",
            f"Order #{order.id} was cancelled. {refunded_total} points refunded." if refunded_total > 0 else f"Order #{order.id} was cancelled.",
            url=reverse("shop:order_detail", args=[order.id]),
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to send cancellation notification: {e}", exc_info=True)

    # Redirect based on where the request came from
    redirect_to = request.GET.get("redirect_to", "shop:order_detail")
    if redirect_to == "shop:order_list":
        return redirect("shop:order_list")
    return redirect("shop:order_detail", order_id=order.id)

# STORY: Order Status (list)
@login_required
def order_list(request):
    """
    Full order history for the logged-in driver with filters + pagination.
    GET params:
        status=<pending|confirmed|shipped|delivered|cancelled>
        sponsor=<substring>
        date_from=YYYY-MM-DD
        date_to=YYYY-MM-DD
        sort=<newest|oldest|points_low|points_high>
        per_page=<int>
        page=<int>
    """
    qs = Order.objects.filter(driver=request.user)

    # filters 
    status = request.GET.get("status", "").strip()
    if status:
        qs = qs.filter(status=status)

    sponsor = request.GET.get("sponsor", "").strip()
    if sponsor:
        qs = qs.filter(sponsor_name__icontains=sponsor)

    date_from_str = request.GET.get("date_from", "").strip()
    date_to_str = request.GET.get("date_to", "").strip()

    if date_from_str:
        d = parse_date(date_from_str) 
        if d:
            start_dt = timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.min.time()))
            qs = qs.filter(placed_at__gte=start_dt)

    if date_to_str:
        d = parse_date(date_to_str)
        if d:
            end_dt = timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.max.time()))
            qs = qs.filter(placed_at__lte=end_dt)

    # Sorting
    sort_by = request.GET.get("sort", "newest").strip()
    if sort_by == "newest":
        qs = qs.order_by("-placed_at")
    elif sort_by == "oldest":
        qs = qs.order_by("placed_at")
    elif sort_by == "points_low":
        qs = qs.order_by("points_spent")
    elif sort_by == "points_high":
        qs = qs.order_by("-points_spent")
    else:
        qs = qs.order_by("-placed_at")  # Default to newest

    # pagination 
    try:
        per_page = int(request.GET.get("per_page", "10"))
    except ValueError:
        per_page = 10
    per_page = max(1, min(per_page, 200))

    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "orders": page_obj.object_list,
        "filters": {
            "status": status,
            "sponsor": sponsor,
            "date_from": date_from_str,
            "date_to": date_to_str,
            "per_page": per_page,
            "sort": sort_by,
        },
        "STATUS_CHOICES": [("", "All")] + list(Order.STATUS_CHOICES),
    }
    return render(request, "shop/order_list.html", context)

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, driver=request.user)

    shipping = {
        "name":        getattr(order, "shipping_name",        "") or request.user.get_full_name() or request.user.username,
        "address1":    getattr(order, "shipping_address1",    "") or "",
        "address2":    getattr(order, "shipping_address2",    "") or "",
        "city":        getattr(order, "shipping_city",        "") or "",
        "state":       getattr(order, "shipping_state",       "") or "",
        "postal_code": getattr(order, "shipping_postal_code", "") or "",
        "country":     getattr(order, "shipping_country",     "") or "US",
    }

    expected_delivery = getattr(order, "expected_delivery_date", None)

    if not expected_delivery:
        base = order.placed_at
        by_status_days = {
            "pending":    7,
            "processing": 5,
            "shipped":    3,
            "delivered":  0,   
            "cancelled":  0,
        }
        days = by_status_days.get(order.status, 7)
        expected_delivery = (base + timedelta(days=days)).date()

    # Consider delayed if not fulfilled and older than 5 days
    is_delayed = (
        order.status in ("pending", "processing")
        and order.placed_at < timezone.now() - timedelta(days=5)
    )

    status_class = {
        "pending":    "badge bg-secondary",
        "processing": "badge bg-info",
        "shipped":    "badge bg-primary",
        "delivered":  "badge bg-success",
        "cancelled":  "badge bg-danger",
    }.get(order.status, "badge bg-light text-dark")

    # Precompute line items safely
    items = getattr(order, "items", None)
    line_items = []
    total_points = 0
    if items:
        for it in items.all():
            qty = getattr(it, "quantity", 1) or 1
            pts = getattr(it, "points_each", 0) or 0
            name = getattr(it, "name_snapshot", "Item")
            line_total = qty * pts
            total_points += line_total
            line_items.append({
                "id": it.id,  # Include item ID for reordering
                "name": name,
                "qty": qty,
                "points_each": pts,
                "points_line": line_total,
            })

    context = {
        "order": order,
        "status_class": status_class,
        "expected_delivery": expected_delivery,
        "shipping": shipping,
        "is_delayed": is_delayed,
        "line_items": line_items,
        "total_points": total_points or getattr(order, "points_spent", 0),
    }
    return render(request, "shop/order_detail.html", context)


# STORY: Mark Order as Received
@login_required
@transaction.atomic
def mark_order_received(request, order_id):
    order = get_object_or_404(Order, id=order_id, driver=request.user)
    if request.method == "POST":
        if order.can_mark_received():
            order.status = "delivered"
            order.save(update_fields=["status", "updated_at"])
            messages.success(request, "Thanks! Order marked as received.")
        else:
            messages.error(request, "This order cannot be marked as received.")
        return redirect("shop:order_detail", order_id=order.id)
    return redirect("shop:order_detail", order_id=order.id)

# STORY: Clear Cart (and cart view)
@login_required
def cart_view(request):
    items = CartItem.objects.filter(driver=request.user).order_by("-added_at")
    total_points = sum(i.points_each * i.quantity for i in items)
    total_balance = get_driver_points_balance(request.user)
    remaining_points = max(0, total_balance - total_points)
    
    # Get/create profile + form
    profile, _ = DriverProfile.objects.get_or_create(user=request.user)
    from accounts.forms import AddressForm

    if request.method == "POST" and request.POST.get("action") == "update_address":
        form = AddressForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Delivery address updated.")
            return redirect("shop:cart")
    else:
        form = AddressForm(instance=profile)

    return render(
        request,
        "shop/cart.html",
        {
            "items": items,
            "total_points": total_points,
            "total_balance": total_balance,
            "remaining_points": remaining_points,
            "address_form": form,
            "profile": profile,
        },
    )


@login_required
@transaction.atomic
def clear_cart(request):
    if request.method == "POST":
        deleted, _ = CartItem.objects.filter(driver=request.user).delete()
        if deleted:
            messages.success(request, "Cart cleared.")
        else:
            messages.info(request, "Your cart is already empty.")
        return redirect("shop:cart")
    return redirect("shop:cart")


@login_required
@transaction.atomic
def save_cart_for_later(request):
    """Save current cart items for later checkout."""
    if request.method != "POST":
        return redirect("shop:cart")
    
    cart_items = CartItem.objects.filter(driver=request.user)
    
    if not cart_items.exists():
        messages.warning(request, "Your cart is empty. Nothing to save.")
        return redirect("shop:cart")
    
    # Get cart name from form or use default
    cart_name = request.POST.get("cart_name", "").strip() or f"Saved Cart {timezone.now().strftime('%Y-%m-%d %H:%M')}"
    
    # Create saved cart
    saved_cart = SavedCart.objects.create(
        driver=request.user,
        name=cart_name,
    )
    
    # Copy cart items to saved cart
    total_points = 0
    for cart_item in cart_items:
        SavedCartItem.objects.create(
            saved_cart=saved_cart,
            name_snapshot=cart_item.name_snapshot,
            points_each=cart_item.points_each,
            quantity=cart_item.quantity,
        )
        total_points += cart_item.points_each * cart_item.quantity
    
    saved_cart.total_points = total_points
    saved_cart.save(update_fields=["total_points"])
    
    messages.success(request, f"Cart saved as '{saved_cart.name}' ({total_points} points). You can restore it later when you have enough points.")
    return redirect("shop:saved_carts")


@login_required
def saved_carts_list(request):
    """List all saved carts for the current driver."""
    saved_carts = SavedCart.objects.filter(driver=request.user).annotate(
        item_count=Count("items")
    ).order_by("-updated_at")
    
    return render(request, "shop/saved_carts.html", {
        "saved_carts": saved_carts,
    })


@login_required
@transaction.atomic
def restore_saved_cart(request, saved_cart_id):
    """Restore a saved cart to the active cart."""
    if request.method != "POST":
        return redirect("shop:saved_carts")
    
    saved_cart = get_object_or_404(SavedCart, id=saved_cart_id, driver=request.user)
    
    # Get existing cart items to check for duplicates
    existing_items = {item.name_snapshot: item for item in CartItem.objects.filter(driver=request.user)}
    
    restored_count = 0
    skipped_count = 0
    
    for saved_item in saved_cart.items.all():
        if saved_item.name_snapshot in existing_items:
            # Update quantity if item already exists
            existing_item = existing_items[saved_item.name_snapshot]
            existing_item.quantity += saved_item.quantity
            existing_item.points_each = saved_item.points_each  # Update price in case it changed
            existing_item.save()
            restored_count += 1
        else:
            # Create new cart item
            CartItem.objects.create(
                driver=request.user,
                name_snapshot=saved_item.name_snapshot,
                points_each=saved_item.points_each,
                quantity=saved_item.quantity,
            )
            restored_count += 1
    
    if restored_count > 0:
        messages.success(request, f"Restored {restored_count} item(s) from '{saved_cart.name}' to your cart.")
    else:
        messages.info(request, "No items were restored.")
    
    return redirect("shop:cart")


@login_required
@transaction.atomic
def delete_saved_cart(request, saved_cart_id):
    """Delete a saved cart."""
    if request.method != "POST":
        return redirect("shop:saved_carts")
    
    saved_cart = get_object_or_404(SavedCart, id=saved_cart_id, driver=request.user)
    cart_name = saved_cart.name
    saved_cart.delete()
    
    messages.success(request, f"Saved cart '{cart_name}' has been deleted.")
    return redirect("shop:saved_carts")


@login_required
@transaction.atomic
def reorder_item(request, order_item_id):
    """Add a single item from a past order back to the cart."""
    if request.method != "POST":
        return redirect("shop:order_list")
    
    order_item = get_object_or_404(OrderItem, id=order_item_id, order__driver=request.user)
    order = order_item.order
    
    # Check if item already exists in cart
    existing_item = CartItem.objects.filter(
        driver=request.user,
        name_snapshot=order_item.name_snapshot
    ).first()
    
    if existing_item:
        # Update quantity
        existing_item.quantity += order_item.quantity
        existing_item.points_each = order_item.points_each  # Update price in case it changed
        existing_item.save()
        messages.success(request, f"Added {order_item.quantity} more '{order_item.name_snapshot}' to your cart (quantity updated).")
    else:
        # Create new cart item
        CartItem.objects.create(
            driver=request.user,
            name_snapshot=order_item.name_snapshot,
            points_each=order_item.points_each,
            quantity=order_item.quantity,
        )
        messages.success(request, f"Added '{order_item.name_snapshot}' to your cart.")
    
    # Store order ID in session to pre-fill shipping info at checkout
    request.session['reorder_order_id'] = order.id
    
    return redirect("shop:checkout")


@login_required
@transaction.atomic
def reorder_all(request, order_id):
    """Add all items from a past order back to the cart."""
    if request.method != "POST":
        return redirect("shop:order_list")
    
    order = get_object_or_404(Order, id=order_id, driver=request.user)
    
    existing_items = {item.name_snapshot: item for item in CartItem.objects.filter(driver=request.user)}
    added_count = 0
    
    for order_item in order.items.all():
        if order_item.name_snapshot in existing_items:
            # Update quantity
            existing_item = existing_items[order_item.name_snapshot]
            existing_item.quantity += order_item.quantity
            existing_item.points_each = order_item.points_each
            existing_item.save()
            added_count += 1
        else:
            # Create new cart item
            CartItem.objects.create(
                driver=request.user,
                name_snapshot=order_item.name_snapshot,
                points_each=order_item.points_each,
                quantity=order_item.quantity,
            )
            added_count += 1
    
    if added_count > 0:
        messages.success(request, f"Added {added_count} item(s) from Order #{order.id} to your cart.")
        
        # Store order ID in session to pre-fill shipping info at checkout
        request.session['reorder_order_id'] = order.id
        
        return redirect("shop:checkout")
    else:
        messages.info(request, "No items were added to your cart.")
    
    return redirect("shop:cart")

@login_required
def wishlist_list(request):
    """
    /wishlists/ - lists all wishlists, create, delete, add/remove items from wishlists
    """
    action = request.POST.get("action")

    if request.method == "POST" and action:
        if action == "create_wishlist":
            name = (request.POST.get("name") or "").strip()
            if not name:
                messages.error(request, "Please enter a wishlist name.")
            else:
                Wishlist.objects.get_or_create(user=request.user, name=name)
                messages.success(request, f"Wishlist '{name}' created.")
            return redirect("shop:wishlist_list")

        elif action == "delete_wishlist":
            wid = request.POST.get("wishlist_id")
            wl = get_object_or_404(Wishlist, id=wid, user=request.user)
            nm = wl.name
            wl.delete()
            messages.success(request, f"Deleted wishlist '{nm}'.")
            return redirect("shop:wishlist_list")

        elif action == "add_item":
            wid = request.POST.get("wishlist_id")
            wl = get_object_or_404(Wishlist, id=wid, user=request.user)

            name = (request.POST.get("name_snapshot") or "").strip()
            points = int(request.POST.get("points_each") or 0)
            qty = max(1, int(request.POST.get("quantity") or 1))

            if not name:
                messages.error(request, "Item name is required.")
            else:
                WishListItem.objects.create(
                    wishlist=wl,
                    name_snapshot=name,
                    points_each=points,
                    quantity=qty,
                    # product_id=request.POST.get("product_id",""),
                    # product_url=request.POST.get("product_url",""),
                    # thumb_url=request.POST.get("thumb_url",""),
                )
                wl.save(update_fields=["updated_at"])
                messages.success(request, f"Added '{name}' to '{wl.name}'.")
            return redirect("shop:wishlist_list")

        elif action == "remove_item":
            wid = request.POST.get("wishlist_id")
            iid = request.POST.get("item_id")
            wl = get_object_or_404(Wishlist, id=wid, user=request.user)
            it = get_object_or_404(WishListItem, id=iid, wishlist=wl)
            it.delete()
            wl.save(update_fields=["updated_at"])
            messages.success(request, "Item removed.")
            return redirect("shop:wishlist_list")

    # GET: fetch ALL wishlists + their items
    wishlists = (
        Wishlist.objects
        .filter(user=request.user)
        .prefetch_related("items")
        .order_by("-updated_at", "-created_at")
    )

    return render(
        request,
        "shop/wishlist_list.html",
        {"wishlists": wishlists},
    )


@login_required
def select_wishlist(request):
    """
    Page to select a wishlist when adding a product from catalog.
    GET params: ebay_item_id, product_name, points, product_url, thumb_url
    """
    # Get product info from query params
    ebay_item_id = request.GET.get("ebay_item_id", "").strip()
    product_name = request.GET.get("product_name", "").strip()
    points = request.GET.get("points", "0")
    product_url = request.GET.get("product_url", "").strip()
    thumb_url = request.GET.get("thumb_url", "").strip()
    
    if not ebay_item_id:
        messages.error(request, "Missing product information.")
        return redirect("shop:catalog_search")
    
    # Handle POST: add to selected wishlist
    if request.method == "POST":
        # Get product info from POST (in case it wasn't in GET)
        ebay_item_id = request.POST.get("ebay_item_id", ebay_item_id)
        product_name = request.POST.get("product_name", product_name)
        points = request.POST.get("points", points)
        product_url = request.POST.get("product_url", product_url)
        thumb_url = request.POST.get("thumb_url", thumb_url)
        
        wishlist_id = request.POST.get("wishlist_id")
        action = request.POST.get("action")
        
        if action == "create_wishlist":
            name = (request.POST.get("name") or "").strip()
            if not name:
                messages.error(request, "Please enter a wishlist name.")
                # Re-render with error
            else:
                wishlist, created = Wishlist.objects.get_or_create(user=request.user, name=name)
                if created:
                    messages.success(request, f"Wishlist '{name}' created.")
                # Continue to add item to this wishlist
                wishlist_id = wishlist.id
        
        if wishlist_id:
            try:
                wishlist = get_object_or_404(Wishlist, id=wishlist_id, user=request.user)
                
                # Check if item already exists in this wishlist
                existing = WishListItem.objects.filter(
                    wishlist=wishlist,
                    product_id=ebay_item_id
                ).first()
                
                if existing:
                    messages.info(request, f"'{product_name}' is already in '{wishlist.name}'.")
                else:
                    WishListItem.objects.create(
                        wishlist=wishlist,
                        product_id=ebay_item_id,
                        product_url=product_url[:1000] if product_url else "",
                        thumb_url=thumb_url[:1000] if thumb_url else "",
                        name_snapshot=product_name[:255],
                        points_each=int(points) if points.isdigit() else 0,
                        quantity=1
                    )
                    wishlist.save(update_fields=["updated_at"])
                    messages.success(request, f"Added '{product_name}' to '{wishlist.name}'.")
                
                # Redirect back to catalog with the search query if available
                return_url = request.POST.get("return_url") or request.GET.get("return_url", reverse("shop:catalog_search"))
                return redirect(return_url)
                
            except Exception as e:
                messages.error(request, f"Error adding to wishlist: {str(e)}")
    
    # GET: show wishlists for selection
    wishlists = (
        Wishlist.objects
        .filter(user=request.user)
        .annotate(item_count=Count("items"))
        .order_by("-updated_at", "-created_at")
    )
    
    context = {
        "wishlists": wishlists,
        "product": {
            "ebay_item_id": ebay_item_id,
            "name": product_name,
            "points": points,
            "product_url": product_url,
            "thumb_url": thumb_url,
        },
        "return_url": request.GET.get("return_url", reverse("shop:catalog_search")),
    }
    
    return render(request, "shop/select_wishlist.html", context)


@login_required
def catalog_search(request):
    """
    Main catalog search page - shows search form and results.
    """
    query       = (request.GET.get("q") or "").strip()
    category_id = (request.GET.get("cat") or "").strip()
    page_num    = request.GET.get("page", "1")
    sort_by     = request.GET.get("sort", "newest")  # newest, oldest, points_low, points_high

    # --- point-range filters ---
    def _to_int(val):
        try:
            return int(val)
        except (TypeError, ValueError):
            return None
    min_points = _to_int(request.GET.get("min_points"))
    max_points = _to_int(request.GET.get("max_points"))

    try:
        page_num = int(page_num)
    except ValueError:
        page_num = 1

    limit  = 20
    offset = (page_num - 1) * limit

    # favorites for star toggle
    user_favorites = set(
        Favorite.objects.filter(user=request.user).values_list("product_id", flat=True)
    )

    context = {
        "query": query,
        "category_id": category_id,
        "category_choices": EBAY_CATEGORY_CHOICES,
        "page": page_num,
        "sort_by": sort_by,
        "results": None,
        "error": None,
        "user_favorites": user_favorites,   
        "min_points": "" if min_points is None else min_points,
        "max_points": "" if max_points is None else max_points,
    }

    context["points_balance"] = get_driver_points_balance(request.user)

    # Get driver catalog items (always include these) - apply sorting
    driver_catalog_items = DriverCatalogItem.objects.filter(is_active=True)
    
    # Apply sorting to driver catalog items
    if sort_by == "newest":
        driver_catalog_items = driver_catalog_items.order_by("-created_at")
    elif sort_by == "oldest":
        driver_catalog_items = driver_catalog_items.order_by("created_at")
    elif sort_by == "points_low":
        driver_catalog_items = driver_catalog_items.order_by("points_cost")
    elif sort_by == "points_high":
        driver_catalog_items = driver_catalog_items.order_by("-points_cost")
    
    # Convert driver catalog items to product format
    driver_products = []
    for item in driver_catalog_items:
        driver_products.append({
            "ebay_item_id": f"CATALOG-{item.id}",
            "name": item.name,
            "price_usd": float(item.price_usd),
            "price_points": item.points_cost,
            "description": item.description,
            "image_url": item.image_url or "",
            "category": item.category or "Catalog",
            "condition": item.condition or "New",
            "is_available": True,
            "view_url": item.product_url or "",
            "is_catalog_item": True,  # Flag to identify catalog items
            "created_at": item.created_at,  # Include created_at for sorting
        })
    
    # If no query, show random/default products + driver catalog items
    if not query:
        # Use a default search term to show products
        default_query = "electronics"
        all_products = list(driver_products)  # Start with driver catalog items
        
        try:
            results = ebay_service.search_products(
                default_query,
                limit=limit,
                offset=offset,
                category_ids=category_id or None,
            )

            ebay_products = [
                ebay_service.format_product(item)
                for item in results.get("itemSummaries", [])
            ]

            # Combine driver catalog items with eBay products
            all_products.extend(ebay_products)
            
            # Only shuffle if no specific sort is requested (default behavior)
            if sort_by == "newest":
                # Don't shuffle - sorting will be applied later
                pass
            else:
                # Shuffle for randomness when not sorting by newest
                import random
                random.shuffle(all_products)

            # --- apply point-range filter on formatted products ---
            def _eligible(p):
                pts = p.get("price_points")
                if pts is None:
                    return False
                if min_points is not None and pts < min_points:
                    return False
                if max_points is not None and pts > max_points:
                    return False
                return True

            filtered = [p for p in all_products if _eligible(p)]
            
            # Apply sorting to filtered products
            if sort_by == "newest":
                # For catalog items, sort by created_at (newest first)
                # For eBay items, we don't have created_at, so keep them as-is
                filtered.sort(key=lambda p: (
                    p.get("created_at", timezone.now()) if p.get("is_catalog_item") else timezone.now() - timedelta(days=365)
                ), reverse=True)
            elif sort_by == "oldest":
                filtered.sort(key=lambda p: (
                    p.get("created_at", timezone.now()) if p.get("is_catalog_item") else timezone.now()
                ), reverse=False)
            elif sort_by == "points_low":
                filtered.sort(key=lambda p: p.get("price_points", 0))
            elif sort_by == "points_high":
                filtered.sort(key=lambda p: p.get("price_points", 0), reverse=True)

            context["results"] = {
                "products": filtered[:20],  # Limit to 20 for default view
                "total": len(filtered),
                "has_next": False,
                "has_prev": False,
            }
            context["is_default_view"] = True
        except Exception as e:
            # If eBay fails, still show driver catalog items
            filtered = [p for p in driver_products if p.get("price_points", 0) >= (min_points or 0) and (max_points is None or p.get("price_points", 0) <= max_points)]
            
            # Apply sorting to filtered products
            if sort_by == "newest":
                filtered.sort(key=lambda p: p.get("created_at", timezone.now()), reverse=True)
            elif sort_by == "oldest":
                filtered.sort(key=lambda p: p.get("created_at", timezone.now()), reverse=False)
            elif sort_by == "points_low":
                filtered.sort(key=lambda p: p.get("price_points", 0))
            elif sort_by == "points_high":
                filtered.sort(key=lambda p: p.get("price_points", 0), reverse=True)
            
            context["results"] = {
                "products": filtered[:20],
                "total": len(filtered),
                "has_next": False,
                "has_prev": False,
            }
            context["is_default_view"] = True
            if str(e):
                context["error"] = str(e)
        
        return render(request, "shop/catalog_search.html", context)

    # User has entered a query - perform search
    # Filter driver catalog items by query if provided
    query_lower = query.lower()
    matching_driver_items = [
        p for p in driver_products
        if query_lower in p["name"].lower() or query_lower in (p.get("description", "") or "").lower() or query_lower in (p.get("category", "") or "").lower()
    ]
    all_products = list(matching_driver_items)  # Start with matching driver catalog items
    
    try:
        results = ebay_service.search_products(
            query,
            limit=limit,
            offset=offset,
            category_ids=category_id or None,
        )

        ebay_products = [
            ebay_service.format_product(item)
            for item in results.get("itemSummaries", [])
        ]
        
        # Combine driver catalog items with eBay results
        all_products.extend(ebay_products)

        # --- apply point-range filter on formatted products ---
        def _eligible(p):
            pts = p.get("price_points")
            if pts is None:
                return False
            if min_points is not None and pts < min_points:
                return False
            if max_points is not None and pts > max_points:
                return False
            return True

        filtered = [p for p in all_products if _eligible(p)]
        
        # Apply sorting to filtered products
        if sort_by == "newest":
            # For catalog items, sort by created_at (newest first)
            # For eBay items, we don't have created_at, so keep them as-is
            filtered.sort(key=lambda p: (
                p.get("created_at", timezone.now()) if p.get("is_catalog_item") else timezone.now() - timedelta(days=365)
            ), reverse=True)
        elif sort_by == "oldest":
            filtered.sort(key=lambda p: (
                p.get("created_at", timezone.now()) if p.get("is_catalog_item") else timezone.now()
            ), reverse=False)
        elif sort_by == "points_low":
            filtered.sort(key=lambda p: p.get("price_points", 0))
        elif sort_by == "points_high":
            filtered.sort(key=lambda p: p.get("price_points", 0), reverse=True)
        
        # Calculate total (driver catalog items + eBay results)
        total_count = len(matching_driver_items) if query else len(driver_products)
        total_count += results.get("total", 0)

        context["results"] = {
            "products": filtered,
            "total": total_count,
            "has_next": results.get("next") is not None,
            "has_prev": page_num > 1,
        }
        context["is_default_view"] = False

    except Exception as e:
        # If eBay fails, still show matching driver catalog items
        filtered = [p for p in all_products if p.get("price_points", 0) >= (min_points or 0) and (max_points is None or p.get("price_points", 0) <= max_points)]
        context["results"] = {
            "products": filtered,
            "total": len(filtered),
            "has_next": False,
            "has_prev": False,
        }
        context["is_default_view"] = False
        context["error"] = str(e)

    return render(request, "shop/catalog_search.html", context)


@login_required
def catalog_search_ajax(request):
    """
    AJAX endpoint for searching products
    """
    query = request.GET.get('q', '').strip()
    category_id= request.GET.get('cat', '').strip()
    limit = min(int(request.GET.get('limit', 20)), 50)
    offset = int(request.GET.get('offset', 0))
    
    if not query:
        return JsonResponse({'error': 'Search query required'}, status=400)
    
    try:
        results = ebay_service.search_products(query, limit=limit, offset=offset, category_ids=category_id or None)
        
        products = [
            ebay_service.format_product(item)
            for item in results.get('itemSummaries', [])
        ]
        
        return JsonResponse({
            'success': True,
            'products': products,
            'total': results.get('total', 0),
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    

@login_required
def add_to_cart_from_catalog(request):
    """
    Add an eBay product directly to cart
    Simplified version for sandbox compatibility
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        ebay_item_id = data.get('ebay_item_id')
        product_name = data.get('product_name')  
        points = int(data.get('points', 0))
        quantity = int(data.get('quantity', 1))

        if not ebay_item_id or not product_name:
            return JsonResponse({'error': 'Missing required fields'}, status=400)
        
        # Handle catalog items (items with CATALOG- prefix)
        is_catalog_item = ebay_item_id.startswith("CATALOG-")
        if is_catalog_item:
            catalog_item_id = ebay_item_id.replace("CATALOG-", "")
            try:
                catalog_item = DriverCatalogItem.objects.get(id=catalog_item_id, is_active=True)
                # Use catalog item data
                product_name = catalog_item.name
                points = catalog_item.points_cost
            except DriverCatalogItem.DoesNotExist:
                return JsonResponse({'error': 'Catalog item not found'}, status=404)
        
        #current user pts balance
        user_points = (
            SponsorPointsAccount.objects
            .filter(driver=request.user)
            .aggregate(total=Sum("balance"))
            .get("total") or 0
        )

        # Calculate current cart total before adding
        current_total = sum(
            item.points_each * item.quantity
            for item in CartItem.objects.filter(driver=request.user)
        )

        incoming_cost = max(1, quantity) * max(0, points)
        if current_total + incoming_cost > user_points:
            return JsonResponse({'error': 'Insufficient points.'}, status=400)

        # Add directly to cart without checking eBay availability
        cart_item, created = CartItem.objects.get_or_create(
            driver=request.user,
            name_snapshot=product_name,
            defaults={
                'points_each': points,
                'quantity': quantity
            }
        )

        if not created:
            cart_item.points_each = points  # refresh price in case it changed
            cart_item.quantity += quantity
            cart_item.save(update_fields=["points_each", "quantity"])
        
        total_points = sum(
            item.points_each * item.quantity
            for item in CartItem.objects.filter(driver=request.user)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Added to cart!',
            'cart_total': total_points
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def add_to_wishlist_from_catalog(request):
    """
    Add an eBay product to a wishlist
    POST with: wishlist_id, ebay_item_id
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        wishlist_id = data.get('wishlist_id')
        ebay_item_id = data.get('ebay_item_id')
        
        if not wishlist_id or not ebay_item_id:
            return JsonResponse({'error': 'Missing required fields'}, status=400)
        
        wishlist = get_object_or_404(Wishlist, id=wishlist_id, user=request.user)
        
        product = ebay_service.get_product_details(ebay_item_id)
        formatted = ebay_service.format_product(product)
        
        WishListItem.objects.create(
            wishlist=wishlist,
            product_id=formatted['ebay_item_id'],
            product_url=formatted['ebay_url'],
            thumb_url=formatted['image_url'],
            name_snapshot=formatted['name'],
            points_each=formatted['price_points'],
            quantity=1
        )
        
        wishlist.save(update_fields=['updated_at'])
        
        return JsonResponse({
            'success': True,
            'message': f"Added to wishlist '{wishlist.name}'"
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def order_receipt_pdf(request, order_id: int):
    """Generate a PDF receipt for the logged-in driver's order."""
    order = get_object_or_404(Order, id=order_id, driver=request.user)
    items = order.items.all()
    subtotal_points = sum(i.points_each * i.quantity for i in items)

    html = render_to_string(
        "shop/order_receipt.html",
        {
            "order": order,
            "items": items,
            "subtotal_points": subtotal_points,
            "user": request.user,
            "base_url": request.build_absolute_uri("/"),
        },
    )

    pdf_io = BytesIO()
    # Let xhtml2pdf resolve relative URLs (images, css) via link_callback
    result = pisa.CreatePDF(src=html, dest=pdf_io, encoding="UTF-8")

    if result.err:
        return HttpResponse(html)

    pdf = pdf_io.getvalue()
    filename = f"order_{order.id}_receipt.pdf"
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

@login_required
def favorites_list(request):
    """List current user's favorites."""
    favorites = Favorite.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "shop/favorites_list.html", {"favorites": favorites})


@login_required
def add_favorite(request):
    """
    Toggle: If product already in favorites → remove it.
    Else → add it as a new favorite (Option A schema).
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    product_id  = (request.POST.get("product_id") or "").strip()
    name        = (request.POST.get("name") or "").strip()
    product_url = (request.POST.get("product_url") or "").strip()
    thumb_url   = (request.POST.get("thumb_url") or "").strip()
    points_each = request.POST.get("points_each")

    if not product_id:
        messages.error(request, "Missing product ID.")
        return redirect("shop:favorites_list")

    # Try to remove/untoggle if it exists already (favorite → unfavorite)
    existing = Favorite.objects.filter(user=request.user, product_id=product_id).first()
    if existing:
        existing.delete()
        messages.info(request, "Removed from favorites.")
    else:
        try:
            points_each = int(points_each or 0)
        except ValueError:
            points_each = 0

        Favorite.objects.create(
            user=request.user,
            product_id=product_id,
            name_snapshot=name,
            product_url=product_url,
            thumb_url=thumb_url,
            points_each=points_each,
        )
        messages.success(request, "Added to favorites.")

    # Redirect back to where the user came from
    ref = request.META.get("HTTP_REFERER", "")
    if ref and url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()}):
        return redirect(ref)
    return redirect("shop:favorites_list")


@login_required
def remove_favorite(request, product_id: str):
    """(Still okay to keep this) Explicit removal of favorite if needed."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    Favorite.objects.filter(user=request.user, product_id=product_id).delete()
    messages.info(request, "Removed from favorites.")

    ref = request.META.get("HTTP_REFERER", "")
    if ref and url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()}):
        return redirect(ref)
    return redirect("shop:favorites_list")


def _parse_yyyy_mm_dd(s):
    """Parse 'YYYY-MM-DD' string to date, or None."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _daterange_from_request(request, default_days=30):
    """
    Extracts start/end from ?start=YYYY-MM-DD & ?end=YYYY-MM-DD,
    or defaults to last X days.
    Returns (start_date, end_date, start_dt, end_dt).
    """
    today = timezone.localdate()
    start = _parse_yyyy_mm_dd(request.GET.get("start", "")) or (today - timedelta(days=default_days))
    end = _parse_yyyy_mm_dd(request.GET.get("end", "")) or today

    start_dt = timezone.make_aware(datetime.combine(start, time.min))
    end_dt = timezone.make_aware(datetime.combine(end, time.max))
    return start, end, start_dt, end_dt

def _csv_or_render(request, filename_base, columns, rows, template_name, context):
    """
    If ?format=csv → return CSV file.
    Otherwise render HTML template and pass columns + rows.
    """
    want_csv = (request.GET.get("format") or "").lower() == "csv"
    if want_csv:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename_base}.csv"'
        writer = csv.writer(response)
        writer.writerow(columns)
        for r in rows:
            writer.writerow([("" if c is None else c) for c in r])
        return response

    # For HTML
    context.update({"columns": columns, "rows": rows})
    from django.shortcuts import render
    return render(request, template_name, context)


# ------------------------------
# REPORT: DRIVER POINT TRACKING
# ------------------------------
from django.contrib.auth.decorators import login_required
from accounts.models import PointsLedger, DriverProfile
from django.contrib.auth.models import User

@login_required
def report_driver_points(request):
    """
    Driver Point Tracking Report
    - Admin or Sponsor
    - Filter by sponsor, driver, date range
    - CSV or HTML
    """
    user = request.user
    is_admin = user.is_staff

    # --- Input filters ---
    driver_username = (request.GET.get("driver") or "").strip()
    start, end, start_dt, end_dt = _daterange_from_request(request)

    # Sponsor scoping:
    if is_admin:
        sponsor_scope = (request.GET.get("sponsor") or "").strip()
    else:
        sponsor_scope = getattr(getattr(user, "driver_profile", None), "sponsor_name", "") or ""

    # --- Build QuerySet ---
    qs = PointsLedger.objects.filter(created_at__range=(start_dt, end_dt))

    if driver_username:
        qs = qs.filter(user__username=driver_username)

    if sponsor_scope:
        qs = qs.filter(user__driver_profile__sponsor_name=sponsor_scope)

    qs = qs.select_related("user", "user__driver_profile").order_by("-created_at")

    # --- Build Data Table ---
    columns = ["Date", "Driver", "Sponsor", "Δ Points", "Reason"]
    rows = []
    for rec in qs:
        sponsor_name = getattr(getattr(rec.user, "driver_profile", None), "sponsor_name", "") or ""
        rows.append([
            timezone.localtime(rec.created_at).strftime("%Y-%m-%d %H:%M"),
            rec.user.username,
            sponsor_name,
            rec.delta,
            rec.reason or "",
        ])

    # Sponsor dropdown options
    sponsor_names = (
        DriverProfile.objects.exclude(sponsor_name="")
        .values_list("sponsor_name", flat=True)
        .distinct()
        .order_by("sponsor_name")
    )

    context = {
        "title": "Driver Point Tracking",
        "is_admin": is_admin,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sponsor": sponsor_scope,
        "sponsor_names": sponsor_names,
        "driver": driver_username,
    }

    return _csv_or_render(
        request,
        f"driver_points_{start}_{end}",
        columns,
        rows,
        "reports/report_driver_points.html",
        context,
    )

def _staff_only(u):
    return u.is_staff or u.is_superuser

@login_required
@user_passes_test(_staff_only)
def report_sales_by_sponsor(request):
    start, end, start_dt, end_dt = _daterange_from_request(request, default_days=30)
    sponsor = (request.GET.get("sponsor") or "").strip()
    detail  = (request.GET.get("detail") or "summary") == "detail"

    # orders in window 
    qs = Order.objects.filter(
        placed_at__range=(start_dt, end_dt)
    ).exclude(status="cancelled")

    if sponsor:
        qs = qs.filter(sponsor_name=sponsor)

    # summary: group by sponsor
    if not detail:
        grouped = (qs.values("sponsor_name")
                     .annotate(total_points=Sum("points_spent"),
                               orders=Count("id"))
                     .order_by("sponsor_name"))
        columns = ["Sponsor", "Orders", "Total Points"]
        rows = [[g["sponsor_name"] or "(none)", g["orders"], g["total_points"] or 0] for g in grouped]
        filename = f"sales_by_sponsor_summary_{start}_{end}"
        template = "reports/report_sales_by_sponsor.html"
    else:
        qs = qs.select_related("driver").order_by("sponsor_name", "-placed_at", "id")
        columns = ["Date", "Sponsor", "Driver", "Order ID", "Status", "Points"]
        rows = [[
            timezone.localtime(o.placed_at).strftime("%Y-%m-%d"),
            o.sponsor_name or "",
            o.driver.username,
            o.id,
            o.status,
            o.points_spent,
        ] for o in qs]
        filename = f"sales_by_sponsor_detail_{start}_{end}"
        template = "reports/report_sales_by_sponsor.html"

    sponsor_names = (Order.objects.exclude(sponsor_name="")
                     .values_list("sponsor_name", flat=True)
                     .distinct().order_by("sponsor_name"))

    ctx = {
        "title": "Sales by Sponsor",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sponsor": sponsor,
        "sponsor_names": sponsor_names,
        "detail": "detail" if detail else "summary",
    }
    return _csv_or_render(request, filename, columns, rows, template, ctx)

@login_required
@user_passes_test(_staff_only)
def report_sales_by_driver(request):
    start, end, start_dt, end_dt = _daterange_from_request(request, default_days=30)
    sponsor  = (request.GET.get("sponsor") or "").strip()
    driver   = (request.GET.get("driver")  or "").strip()
    detail   = (request.GET.get("detail")  or "summary") == "detail"

    qs = Order.objects.filter(placed_at__range=(start_dt, end_dt)).exclude(status="cancelled")
    if sponsor:
        qs = qs.filter(sponsor_name=sponsor)
    if driver:
        qs = qs.filter(driver__username=driver)

    if not detail:
        grouped = (qs.values("driver__username", "sponsor_name")
                     .annotate(total_points=Sum("points_spent"),
                               orders=Count("id"))
                     .order_by("sponsor_name", "driver__username"))
        columns = ["Sponsor", "Driver", "Orders", "Total Points"]
        rows = [[g["sponsor_name"] or "", g["driver__username"] or "", g["orders"], g["total_points"] or 0] for g in grouped]
        filename = f"sales_by_driver_summary_{start}_{end}"
    else:
        qs = qs.select_related("driver").order_by("sponsor_name", "driver__username", "-placed_at")
        columns = ["Date", "Sponsor", "Driver", "Order ID", "Status", "Points"]
        rows = [[
            timezone.localtime(o.placed_at).strftime("%Y-%m-%d"),
            o.sponsor_name or "",
            o.driver.username,
            o.id,
            o.status,
            o.points_spent,
        ] for o in qs]
        filename = f"sales_by_driver_detail_{start}_{end}"

    sponsor_names = (Order.objects.exclude(sponsor_name="")
                     .values_list("sponsor_name", flat=True)
                     .distinct().order_by("sponsor_name"))

    driver_names = (Order.objects.values_list("driver__username", flat=True)
                    .distinct().order_by("driver__username"))

    ctx = {
        "title": "Sales by Driver",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sponsor": sponsor,
        "driver": driver,
        "sponsor_names": sponsor_names,
        "driver_names": driver_names,
        "detail": "detail" if detail else "summary",
    }
    return _csv_or_render(request, filename, columns, rows, "reports/report_sales_by_driver.html", ctx)

@login_required
@user_passes_test(_staff_only)
def report_invoices(request):
    # Month/year inputs (default = current month)
    month = int((request.GET.get("month") or timezone.localdate().month))
    year  = int((request.GET.get("year")  or timezone.localdate().year))

    start = date(year, month, 1)
    # naive end-of-month
    if month == 12:
        end = date(year+1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month+1, 1) - timedelta(days=1)

    start_dt = timezone.make_aware(datetime.combine(start, time.min))
    end_dt   = timezone.make_aware(datetime.combine(end,   time.max))

    # fee per driver
    fee = getattr(settings, "REPORT_FEE_PER_DRIVER", 5.00)

    # active drivers per sponsor in range (any order in period)
    orders = (Order.objects
              .filter(placed_at__range=(start_dt, end_dt))
              .exclude(status="cancelled")
              .values("sponsor_name", "driver")
              .distinct())

    # count drivers per sponsor
    per_sponsor_driver_counts = {}
    for row in orders:
        s = row["sponsor_name"] or ""
        per_sponsor_driver_counts.setdefault(s, set()).add(row["driver"])

    # build rows per sponsor
    invoices = []
    for sponsor_name, driver_set in per_sponsor_driver_counts.items():
        driver_count = len(driver_set)
        total_due = round(driver_count * fee, 2)
        invoices.append({
            "sponsor": sponsor_name,
            "driver_count": driver_count,
            "fee": f"${fee:,.2f}",
            "total": f"${total_due:,.2f}",
            "period": start.strftime("%b %Y"),
        })

    columns = ["Sponsor", "Period", "# Drivers", "Fee/Driver", "Total Due"]
    rows = [[inv["sponsor"], inv["period"], inv["driver_count"], inv["fee"], inv["total"]] for inv in invoices]
    ctx = {
        "title": "Invoices",
        "month": month,
        "year": year,
        "invoices": invoices,
    }
    return _csv_or_render(request, f"invoices_{year}_{month:02d}", columns, rows, "reports/report_invoices.html", ctx)

@login_required
def checkout(request):
    """
    Show shipping form + cart summary.
    On POST, create Order, move CartItems -> OrderItems, set ETA, deduct points, clear cart.
    """
    driver = request.user

    # Gather cart
    cart_qs = CartItem.objects.filter(driver=driver).order_by("added_at")
    if not cart_qs.exists():
        messages.info(request, "Your cart is empty.")
        return redirect("shop:catalog_search")

    # Compute total points
    total_points = 0
    for c in cart_qs:
        qty = c.quantity if c.quantity and c.quantity > 0 else 1
        total_points += (c.points_each or 0) * qty

    # Calculate point splitting breakdown for display (always calculate for GET and POST)
    total_balance = get_driver_points_balance(driver)
    wallets = list(SponsorPointsAccount.objects
        .filter(driver=driver, balance__gt=0)
        .select_related("sponsor")
        .order_by("-balance"))
    
    point_split_breakdown = []
    remaining_points = total_points
    for wallet in wallets:
        if remaining_points <= 0:
            break
        points_from_wallet = min(remaining_points, wallet.balance)
        point_split_breakdown.append({
            "sponsor": wallet.sponsor.get_full_name() or wallet.sponsor.username,
            "wallet_balance": wallet.balance,
            "points_to_use": points_from_wallet,
        })
        remaining_points -= points_from_wallet

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            # Check total balance across all wallets
            total_balance = get_driver_points_balance(driver)
            
            if total_balance < total_points:
                messages.error(request, f"Insufficient points. You have {total_balance} points but need {total_points} points.")
            else:
                try:
                    with transaction.atomic():
                        # Get all wallets with balance, ordered by balance descending
                        wallets = list(SponsorPointsAccount.objects
                            .select_for_update()
                            .filter(driver=driver, balance__gt=0)
                            .select_related("sponsor")
                            .order_by("-balance"))
                        
                        if not wallets:
                            messages.error(request, "No sponsor wallets found with available points.")
                        else:
                            # Get primary sponsor name from first wallet
                            primary_sponsor_name = getattr(wallets[0].sponsor, "username", "") or ""
                            
                            # Create order first
                            order = Order.objects.create(
                                driver=driver,
                                sponsor_name=primary_sponsor_name,
                                status="pending",
                                points_spent=total_points,
                                ship_name=form.cleaned_data["ship_name"],
                                ship_line1=form.cleaned_data["ship_line1"],
                                ship_line2=form.cleaned_data["ship_line2"],
                                ship_city=form.cleaned_data["ship_city"],
                                ship_state=form.cleaned_data["ship_state"],
                                ship_postal=form.cleaned_data["ship_postal"],
                                ship_country=(form.cleaned_data["ship_country"] or "US").upper(),
                                expected_delivery_date=None, 
                            )

                            # Move cart items → order items
                            bulk_items = []
                            for c in cart_qs:
                                qty = c.quantity if c.quantity and c.quantity > 0 else 1
                                bulk_items.append(OrderItem(
                                    order=order,
                                    name_snapshot=c.name_snapshot,
                                    points_each=c.points_each or 0,
                                    quantity=qty,
                                ))
                            OrderItem.objects.bulk_create(bulk_items)

                            # Set ETA
                            order.expected_delivery_date = order.estimate_delivery_date()
                            order.save(update_fields=["expected_delivery_date"])

                            # Deduct points from wallets, starting with the highest balance
                            remaining_points = total_points
                            
                            for wallet in wallets:
                                if remaining_points <= 0:
                                    break
                                
                                points_to_deduct = min(remaining_points, wallet.balance)
                                wallet.apply_points(
                                    -points_to_deduct,
                                    reason=f"Checkout Order #{order.id}",
                                    created_by=driver,
                                    order=order,
                                )
                                remaining_points -= points_to_deduct

                            # Clear cart
                            cart_qs.delete()

                            # Send order creation notification
                            if send_in_app_notification:
                                try:
                                    from django.urls import reverse
                                    order_url = reverse("shop:order_detail", args=[order.id])
                                    send_in_app_notification(
                                        driver,
                                        "orders",
                                        "Order Placed",
                                        f"Your order #{order.id} has been placed successfully. Total: {total_points} points.",
                                        url=order_url,
                                    )
                                except Exception as e:
                                    import logging
                                    logger = logging.getLogger(__name__)
                                    logger.warning(f"Failed to send order notification: {e}", exc_info=True)

                            messages.success(request, f"Order #{order.id} placed successfully.")
                            return redirect("shop:order_detail", order_id=order.id)
                except Exception as e:
                    messages.error(request, f"An error occurred while processing your order: {str(e)}")
                    import logging
                    logging.exception("Checkout error")
        else:
            # Form is invalid - show errors
            messages.error(request, "Please correct the errors below.")
    else:
        # Check if we're reordering - pre-fill form with previous order's shipping info
        reorder_order_id = request.session.pop('reorder_order_id', None)
        if reorder_order_id:
            try:
                previous_order = Order.objects.get(id=reorder_order_id, driver=driver)
                form = CheckoutForm(initial={
                    'ship_name': previous_order.ship_name,
                    'ship_line1': previous_order.ship_line1,
                    'ship_line2': previous_order.ship_line2 or '',
                    'ship_city': previous_order.ship_city,
                    'ship_state': previous_order.ship_state,
                    'ship_postal': previous_order.ship_postal,
                    'ship_country': previous_order.ship_country or 'US',
                })
                messages.info(request, f"Shipping information from Order #{previous_order.id} has been pre-filled. You can modify it if needed.")
            except Order.DoesNotExist:
                form = CheckoutForm()
        else:
            form = CheckoutForm()

    # Get total balance for display (if not already calculated)
    if 'total_balance' not in locals():
        total_balance = get_driver_points_balance(driver)
    points_needed = max(0, total_points - total_balance)
    remaining_points = max(0, total_balance - total_points)

    return render(request, "shop/checkout.html", {
        "form": form,
        "cart_items": cart_qs,
        "total_points": total_points,
        "total_balance": total_balance,
        "points_needed": points_needed,
        "remaining_points": remaining_points,
        "point_split_breakdown": point_split_breakdown,
    })


def _is_sponsor(user):
    """Check if user is a sponsor."""
    return user.groups.filter(name="sponsor").exists() or user.is_superuser


@login_required
@user_passes_test(_is_sponsor)
def sponsor_catalog(request):
    """Sponsor catalog management - view and manage sponsor-only items."""
    sponsor = request.user
    # Only show items that are NOT yet in the driver catalog
    items = SponsorCatalogItem.objects.filter(
        sponsor=sponsor
    ).exclude(
        driver_catalog_items__isnull=False
    ).order_by("-created_at")
    
    # Handle form submission
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "add":
            form = SponsorCatalogItemForm(request.POST)
            if form.is_valid():
                item = form.save(commit=False)
                item.sponsor = sponsor
                item.save()
                messages.success(request, f"Item '{item.name}' added to your catalog.")
                return redirect("shop:sponsor_catalog")
        elif action == "edit":
            item_id = request.POST.get("item_id")
            item = get_object_or_404(SponsorCatalogItem, id=item_id, sponsor=sponsor)
            form = SponsorCatalogItemForm(request.POST, instance=item)
            if form.is_valid():
                form.save()
                messages.success(request, f"Item '{item.name}' updated.")
                return redirect("shop:sponsor_catalog")
        elif action == "delete":
            item_id = request.POST.get("item_id")
            item = get_object_or_404(SponsorCatalogItem, id=item_id, sponsor=sponsor)
            item_name = item.name
            item.delete()
            messages.success(request, f"Item '{item_name}' deleted.")
            return redirect("shop:sponsor_catalog")
        elif action == "add_to_driver_catalog":
            item_id = request.POST.get("item_id")
            sponsor_item = get_object_or_404(SponsorCatalogItem, id=item_id, sponsor=sponsor)
            
            # Check if already in driver catalog
            existing = DriverCatalogItem.objects.filter(
                source_sponsor_item=sponsor_item
            ).first()
            
            if existing:
                messages.info(request, f"'{sponsor_item.name}' is already in the driver catalog.")
            else:
                # Add to driver catalog
                driver_item = DriverCatalogItem.objects.create(
                    name=sponsor_item.name,
                    description=sponsor_item.description,
                    price_usd=sponsor_item.price_usd,
                    points_cost=sponsor_item.points_cost,
                    image_url=sponsor_item.image_url,
                    product_url=sponsor_item.product_url,
                    category=sponsor_item.category,
                    condition="New",
                    is_active=True,
                    added_by=sponsor,
                    source_sponsor_item=sponsor_item,
                )
                messages.success(request, f"'{sponsor_item.name}' added to driver catalog!")
            
            return redirect("shop:sponsor_catalog")
    else:
        form = SponsorCatalogItemForm()
    
    context = {
        "items": items,
        "form": form,
    }
    return render(request, "shop/sponsor_catalog.html", context)


@login_required
@user_passes_test(_is_sponsor)
def sponsor_catalog_edit(request, item_id):
    """Edit a sponsor catalog item."""
    sponsor = request.user
    item = get_object_or_404(SponsorCatalogItem, id=item_id, sponsor=sponsor)
    
    if request.method == "POST":
        form = SponsorCatalogItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f"Item '{item.name}' updated.")
            return redirect("shop:sponsor_catalog")
    else:
        form = SponsorCatalogItemForm(instance=item)
    
    return render(request, "shop/sponsor_catalog_edit.html", {
        "form": form,
        "item": item,
    })