from django.urls import path
from . import views

urlpatterns = [
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/received/", views.mark_order_received, name="mark_order_received"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/clear/", views.clear_cart, name="clear_cart"),
    path("orders/<int:order_id>/cancel/", views.cancel_order, name="cancel_order"),
]

urlpatterns += [
    path("wishlists/", views.wishlist_list, name="wishlist_list"),
    path("wishlists/<int:wishlist_id>/", views.wishlist_detail, name="wishlist_detail"),
    path("wishlists/<int:wishlist_id>/delete/", views.wishlist_delete, name="wishlist_delete"),
    path("wishlists/<int:wishlist_id>/items/<int:item_id>/remove/",
        views.wishlist_item_remove,
        name="wishlist_item_remove",
    ),
]