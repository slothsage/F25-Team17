from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.html import format_html
from .models import DriverProfile, CustomLabel
from .models import FailedLoginAttempt
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
    # tuple-unpack for type checker
    list_display = (*DjangoUserAdmin.list_display, "last_login", "password_actions")
    list_filter = (*DjangoUserAdmin.list_filter, "last_login")
    ordering = ("-last_login",)

    actions = ["lock_selected_users", "unlock_selected_users"]

    @admin.display(description="Password actions")
    def password_actions(self, obj):
        return format_html(
            '<a class="button" href="{}">Send reset link</a>&nbsp;'
            '<a class="button" href="{}">Temp password</a>',
            reverse("accounts:admin_send_reset_link", args=[obj.pk]),
            reverse("accounts:admin_set_temp_password", args=[obj.pk]),
        )


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "address", "is_locked")
    search_fields = ("user__username", "user__email", "phone", "address")
    readonly_fields = ("is_locked",)
    list_filter = ("is_locked", "is_suspended", "labels")
    filter_horizontal = ("labels",)


@admin.register(CustomLabel)
class CustomLabelAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "created_at")
    search_fields = ("name",)

@admin.register(FailedLoginAttempt)
class FailedLoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("username", "ip_address", "timestamp")
    ordering = ("-timestamp",)
    search_fields = ("username", "ip_address")