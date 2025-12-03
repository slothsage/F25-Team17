from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.generic import RedirectView
from accounts import views as accounts_views

urlpatterns = [
    # Redirect root URL to About page
    path("", RedirectView.as_view(url="/about/", permanent=False), name="home"),
    # our custom admin landing/search
    path("admin/", accounts_views.admin_user_search, name="admin_user_search"),
    path("admin/create-driver/", accounts_views.create_driver, name="create_driver"),
    path("admin/create-sponsor/", accounts_views.create_sponsor, name="create_sponsor"),
    path("admin/create-admin/", accounts_views.create_admin, name="create_admin"),
    path("admin/user/<int:user_id>/toggle-active/", accounts_views.toggle_user_active, name="toggle_user_active"),
    path("admin/user/<int:user_id>/toggle-lock/", accounts_views.toggle_lock_user, name="toggle_lock_user"),
    # real admin site moved to /admin/site/
    path("admin/site/", admin.site.urls),
    path("", include(("accounts.urls", "accounts"), namespace="accounts")),    
    path("", include(("shop.urls", "shop"), namespace="shop")),
    path("about/", accounts_views.about, name="about"),
    path("faqs/", accounts_views.faqs, name="faqs"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/suggest/drivers/", accounts_views.api_driver_suggest, name="api_driver_suggest"),
    path("api/suggest/sponsors/", accounts_views.api_sponsor_suggest, name="api_sponsor_suggest"),
]

handler403 = accounts_views.custom_permission_denied_view

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)