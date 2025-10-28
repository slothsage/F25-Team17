from django.urls import path
from . import views
from .views import order_list, order_detail

urlpatterns = [
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/received/", views.mark_order_received, name="mark_order_received"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/clear/", views.clear_cart, name="clear_cart"),
    path("orders/<int:order_id>/cancel/", views.cancel_order, name="cancel_order"),
    path("catalog/", views.catalog_search, name="catalog_search"),
    path("catalog/search/ajax/", views.catalog_search_ajax, name="catalog_search_ajax"),
    path("catalog/add-to-wishlist/", views.add_to_wishlist_from_catalog, name="add_to_wishlist_from_catalog"),
    path("catalog/add-to-cart/", views.add_to_cart_from_catalog, name="add_to_cart_from_catalog"),
]


urlpatterns += [
    path("wishlists/", views.wishlist_list, name="wishlist_list")
]