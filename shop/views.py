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
from .forms import PointsConfigForm, CheckoutForm
from .models import Order, OrderItem, CartItem, Favorite, PointsConfig
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
from django.db.models import Sum


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

    # Only allow cancel before ship/delivered
    cancellable_statuses = {"pending", "processing"}
    if order.status in cancellable_statuses:
        order.status = "cancelled"
        order.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Order #{order.id} has been cancelled.")

        if send_in_app_notification:
            try:
                send_in_app_notification(
                    request.user,
                    "orders",
                    "Order Cancelled",
                    f"Order #{order.id} was cancelled.",
                    url=reverse("shop:order_detail", args=[order.id]),
                )
            except Exception:
                pass
    else:
        messages.error(request, "This order can’t be cancelled at its current status.")

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
        per_page=<int>
        page=<int>
    """
    qs = Order.objects.filter(driver=request.user).order_by("-placed_at")

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
        "results": None,
        "error": None,
        "user_favorites": user_favorites,   
        "min_points": "" if min_points is None else min_points,
        "max_points": "" if max_points is None else max_points,
    }

    context["points_balance"] = get_driver_points_balance(request.user)

    if not query:
        return render(request, "shop/catalog_search.html", context)

    try:
        results = ebay_service.search_products(
            query,
            limit=limit,
            offset=offset,
            category_ids=category_id or None,
        )

        products = [
            ebay_service.format_product(item)
            for item in results.get("itemSummaries", [])
        ]

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

        filtered = [p for p in products if _eligible(p)]

        context["results"] = {
            "products": filtered,
            "total": results.get("total", 0),
            "has_next": results.get("next") is not None,
            "has_prev": page_num > 1,
        }

    except Exception as e:
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
        form = CheckoutForm()

    # Get total balance for display
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
    })