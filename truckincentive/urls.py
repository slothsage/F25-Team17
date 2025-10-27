from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from accounts import views as accounts_views

urlpatterns = [
    # our custom admin landing/search
    path("admin/", accounts_views.admin_user_search, name="admin_user_search"),
    path("admin/create-driver/", accounts_views.create_driver, name="create_driver"),
    path("admin/create-sponsor/", accounts_views.create_sponsor, name="create_sponsor"),
    path("admin/user/<int:user_id>/toggle-active/", accounts_views.toggle_user_active, name="toggle_user_active"),
    path("admin/user/<int:user_id>/toggle-lock/", accounts_views.toggle_lock_user, name="toggle_lock_user"),
    # real admin site moved to /admin/site/
    path("admin/site/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("shop.urls")),
    path("about/", accounts_views.about, name="about"),
    path("faqs/", accounts_views.faqs, name="faqs"),
    path("i18n/", include("django.conf.urls.i18n"))
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)