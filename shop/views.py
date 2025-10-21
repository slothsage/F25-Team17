from datetime import timedelta, timezone
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from .models import Order, OrderItem, CartItem
from django.urls import reverse
from .models import Wishlist, WishListItem

try:
    from accounts.notifications import send_in_app_notification
except Exception:
    send_in_app_notification = None

@login_required
@transaction.atomic
def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, driver=request.user)

    if request.method != "POST":
        return redirect("order_detail", order_id=order.id)

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
                    url=reverse("order_detail", args=[order.id]),
                )
            except Exception:
                pass
    else:
        messages.error(request, "This order can’t be cancelled at its current status.")

    return redirect("order_detail", order_id=order.id)

# STORY: Order Status (list)
@login_required
def order_list(request):
    status = request.GET.get("status")
    qs = Order.objects.filter(driver=request.user).order_by("-placed_at")
    if status:
        qs = qs.filter(status=status)
    return render(request, "shop/order_list.html", {"orders": qs, "status": status})

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
        return redirect("order_detail", order_id=order.id)
    return redirect("order_detail", order_id=order.id)

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
            return redirect("cart")
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
        return redirect("cart")
    return redirect("cart")

@login_required
def wishlist_list(request):
    """ 
    WISHLIST VIEW LANDING PAGE - shows all wishlists for the logged in user
    """
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Please name your wishlist.")
        else:
            Wishlist.objects.get_or_create(user=request.user, name=name)
            messages.success(request, f'Wishlist "{name}" created.')
            return redirect("wishlist_list")
    
    lists = Wishlist.objects.filter(user=request.user).order_by("-updated_at", "-created_at")
    return render(request, "shop/wishlist_list.html", {"wishlists": lists})

@login_required
def wishlist_detail(request, wishlist_id):
    """
    Details Page - shows all items in a wishlist.
    """
    wl = get_object_or_404(Wishlist, id=wishlist_id, user=request.user)

    if request.method == "POST" and request.POST.get("action") == "add_item":
        # NOTE: When eBay is wired up, fill product_id/product_url/thumb_url here.
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
                # product_id=request.POST.get("product_id", ""),
                # product_url=request.POST.get("product_url", ""),
                # thumb_url=request.POST.get("thumb_url", ""),
            )
            wl.save(update_fields=["updated_at"])
            messages.success(request, f"Added '{name}' to {wl.name}.")
            return redirect("wishlist_detail", wishlist_id=wl.id)
    
    return render(request, "shop/wishlist_detail.html", {"wishlist": wl, "items": wl.items.all()})

@login_required
@transaction.atomic
def wishlist_delete(request, wishlist_id):
    """Delete an entire wishlist (POST only)."""
    wl = get_object_or_404(Wishlist, id=wishlist_id, user=request.user)
    if request.method == "POST":
        name = wl.name
        wl.delete()
        messages.success(request, f"Deleted wishlist '{name}'.")
        return redirect("wishlist_list")
    return redirect("wishlist_detail", wishlist_id=wishlist_id)

@login_required
@transaction.atomic
def wishlist_item_remove(request, wishlist_id, item_id):
    """Remove a single item from a wishlist (POST only)."""
    wl = get_object_or_404(Wishlist, id=wishlist_id, user=request.user)
    item = get_object_or_404(WishListItem, id=item_id, wishlist=wl)
    if request.method == "POST":
        item.delete()
        wl.save(update_fields=["updated_at"])
        messages.success(request, "Item removed.")
        return redirect("wishlist_detail", wishlist_id=wishlist_id)
    return redirect("wishlist_detail", wishlist_id=wishlist_id)
