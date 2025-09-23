from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import reverse
from django.utils.html import format_html

from .models import PasswordPolicy


# Register your models here.

@admin.register(PasswordPolicy)
class PasswordPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "min_length",
        "require_upper",
        "require_lower",
        "require_digit",
        "require_symbol",
        "expiry_days",
        "updated_at",
    )


# Get the user model Django is using (usually auth.User)
User = get_user_model()


# Extend the built-in UserAdmin
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # tuple-unpack to appease the type checker
    list_display = (*DjangoUserAdmin.list_display, "password_actions")

    @admin.display(description="Password actions")
    def password_actions(self, obj):
        return format_html(
            '<a class="button" href="{}">Send reset link</a>&nbsp;'
            '<a class="button" href="{}">Temp password</a>',
            reverse("accounts:admin_send_reset_link", args=[obj.pk]),
            reverse("accounts:admin_set_temp_password", args=[obj.pk]),
        )