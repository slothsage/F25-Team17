from django.urls import path
from . import views
from .views import order_list, order_detail

app_name = "shop"

urlpatterns = [
    path("settings/points/", views.points_settings, name="points_settings"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/received/", views.mark_order_received, name="mark_order_received"),
    path("orders/<int:order_id>/receipt.pdf", views.order_receipt_pdf, name="order_receipt_pdf"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/clear/", views.clear_cart, name="clear_cart"),
    path("orders/<int:order_id>/cancel/", views.cancel_order, name="cancel_order"),
    path("catalog/", views.catalog_search, name="catalog_search"),
    path("catalog/search/ajax/", views.catalog_search_ajax, name="catalog_search_ajax"),
    path("catalog/add-to-wishlist/", views.add_to_wishlist_from_catalog, name="add_to_wishlist_from_catalog"),
    path("catalog/add-to-cart/", views.add_to_cart_from_catalog, name="add_to_cart_from_catalog"),
    path("favorites/", views.favorites_list, name="favorites_list"),
    path("favorites/add/", views.add_favorite, name="add_favorite"),
    path("favorites/remove/<str:product_id>/", views.remove_favorite, name="remove_favorite"),
]


urlpatterns += [
    path("wishlists/", views.wishlist_list, name="wishlist_list")
]