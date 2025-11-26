from django.urls import path
from . import views
from .views import order_list, order_detail

app_name = "shop"

urlpatterns = [
    path("settings/points/", views.points_settings, name="points_settings"),
    path("checkout/", views.checkout, name="checkout"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/received/", views.mark_order_received, name="mark_order_received"),
    path("orders/<int:order_id>/receipt.pdf", views.order_receipt_pdf, name="order_receipt_pdf"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/clear/", views.clear_cart, name="clear_cart"),
    path("cart/save/", views.save_cart_for_later, name="save_cart_for_later"),
    path("saved-carts/", views.saved_carts_list, name="saved_carts"),
    path("saved-carts/<int:saved_cart_id>/restore/", views.restore_saved_cart, name="restore_saved_cart"),
    path("saved-carts/<int:saved_cart_id>/delete/", views.delete_saved_cart, name="delete_saved_cart"),
    path("orders/<int:order_id>/cancel/", views.cancel_order, name="cancel_order"),
    path("orders/<int:order_id>/reorder-all/", views.reorder_all, name="reorder_all"),
    path("order-items/<int:order_item_id>/reorder/", views.reorder_item, name="reorder_item"),
    path("catalog/", views.catalog_search, name="catalog_search"),
    path("catalog/search/ajax/", views.catalog_search_ajax, name="catalog_search_ajax"),
    path("catalog/add-to-wishlist/", views.add_to_wishlist_from_catalog, name="add_to_wishlist_from_catalog"),
    path("catalog/add-to-cart/", views.add_to_cart_from_catalog, name="add_to_cart_from_catalog"),
    path("favorites/", views.favorites_list, name="favorites_list"),
    path("favorites/add/", views.add_favorite, name="add_favorite"),
    path("favorites/remove/<str:product_id>/", views.remove_favorite, name="remove_favorite"),
    # Reports
    path("reports/driver-points/",    views.report_driver_points, name="report_driver_points"),
    path("reports/sales-by-sponsor/", views.report_sales_by_sponsor, name="report_sales_by_sponsor"),
    path("reports/sales-by-driver/",  views.report_sales_by_driver, name="report_sales_by_driver"),
    path("reports/fee-tracking/",     views.report_fee_tracking,    name="report_fee_tracking"),
    path("reports/invoices/",         views.report_invoices,        name="report_invoices"),
]


urlpatterns += [
    path("wishlists/", views.wishlist_list, name="wishlist_list"),
    path("wishlists/select/", views.select_wishlist, name="select_wishlist"),
    
    # Sponsor Catalog
    path("sponsor/catalog/", views.sponsor_catalog, name="sponsor_catalog"),
    path("sponsor/catalog/<int:item_id>/edit/", views.sponsor_catalog_edit, name="sponsor_catalog_edit"),
    path("sponsor/catalog/import/", views.sponsor_catalog_import, name="sponsor_catalog_import"),
    path("sponsor/catalog/import/product/", views.sponsor_catalog_import_product, name="sponsor_catalog_import_product"),
    
    # Sponsor Order Management
    path("sponsor/orders/", views.sponsor_orders, name="sponsor_orders"),
    path("sponsor/orders/<int:order_id>/update/", views.sponsor_update_order, name="sponsor_update_order"),
]