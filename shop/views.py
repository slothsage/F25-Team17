from datetime import timedelta, timezone
from io import BytesIO
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.template.loader import render_to_string
from django.http import HttpResponse
from .models import PointsConfig
from .forms import PointsConfigForm
from .models import Order, OrderItem, CartItem
from django.urls import reverse
from .models import Wishlist, WishListItem
from django.core.paginator import Paginator
from .ebay_service import ebay_service
from django.utils.dateparse import parse_date
from django.http import JsonResponse
from xhtml2pdf import pisa
import json


# A tiny, editable set of eBay category IDs (Browse API uses numeric IDs)
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

# STORY: Order Status (detail) + base for "Mark as Received"
@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, driver=request.user)

    # consider delayed if still not fulfilled and older than 5 days
    is_delayed = (
        order.status in ["pending", "processing"]
        and order.placed_at < timezone.now() - timedelta(days=5)  # use created/placed field your model has
    )

    return render(
        request,
        "shop/order_detail.html",
        {"order": order, "is_delayed": is_delayed},
    )

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
    return render(request, "shop/cart.html", {"items": items, "total_points": total_points})

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
def catalog_search(request):
    """
    Main catalog search page - shows search form and results
    """
    query = request.GET.get("q", "").strip()
    category_id = request.GET.get("cat", "").strip()  
    page_num = request.GET.get("page", "1")

    try:
        page_num = int(page_num)
    except ValueError:
        page_num = 1

    limit = 20
    offset = (page_num - 1) * limit

    context = {
        "query": query,
        "category_id": category_id,                 
        "category_choices": EBAY_CATEGORY_CHOICES,  
        "page": page_num,
        "results": None,
        "error": None,
    }

    if query:
        try:
            # pass category if selected
            results = ebay_service.search_products(
                query,
                limit=limit,
                offset=offset,
                category_id=category_id or None, 
            )

            products = [
                ebay_service.format_product(item)
                for item in results.get("itemSummaries", [])
            ]

            context["results"] = {
                "products": products,
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
        results = ebay_service.search_products(query, limit=limit, offset=offset)
        
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
            # Update quantity if already exists
            cart_item.quantity += quantity
            cart_item.save()
        
        # Calculate cart total
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