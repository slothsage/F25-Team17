from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.html import format_html
from .models import DriverProfile, CustomLabel, SponsorProfile
from .models import FailedLoginAttempt
from .models import PasswordPolicy
from .models import ChatRoom, ChatMessage, MessageReadStatus
from .models import SponsorPointsAccount, SponsorPointsTransaction
from .models import BulkUploadLog


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


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "sponsor", "created_at", "updated_at", "participant_count")
    search_fields = ("name", "sponsor__username")
    list_filter = ("created_at",)
    readonly_fields = ("created_at", "updated_at")
    
    @admin.display(description="Participants")
    def participant_count(self, obj):
        return len(obj.get_participants())


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "chat_room", "message_preview", "created_at")
    search_fields = ("sender__username", "message", "chat_room__name")
    list_filter = ("created_at", "chat_room")
    readonly_fields = ("created_at", "edited_at")
    
    @admin.display(description="Message")
    def message_preview(self, obj):
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message


@admin.register(MessageReadStatus)
class MessageReadStatusAdmin(admin.ModelAdmin):
    list_display = ("message", "user", "is_read", "read_at")
    search_fields = ("user__username", "message__message")
    list_filter = ("is_read", "read_at")
    readonly_fields = ("read_at",)


@admin.register(SponsorProfile)
class SponsorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "points_per_usd", "is_archived", "archived_at", "archived_by")
    search_fields = ("user__username", "user__email")
    list_filter = ("is_archived",)
    readonly_fields = ("archived_at", "archived_by")
    
    def get_points_per_usd(self, obj):
        if obj.points_per_usd:
            return f"{obj.points_per_usd} (custom)"
        from shop.models import PointsConfig
        default = PointsConfig.get_solo().points_per_usd
        return f"{default} (default)"
    get_points_per_usd.short_description = "Points per USD"


@admin.register(CustomLabel)
class CustomLabelAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "created_at")
    search_fields = ("name",)

@admin.register(FailedLoginAttempt)
class FailedLoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("username", "ip_address", "timestamp")
    ordering = ("-timestamp",)
    search_fields = ("username", "ip_address")

@admin.register(SponsorPointsAccount)
class SponsorPointsAccountAdmin(admin.ModelAdmin):
    list_display = ("driver", "sponsor", "balance", "is_primary", "updated_at")
    list_filter = ("is_primary",)
    search_fields = ("driver__username", "sponsor__username")

@admin.register(SponsorPointsTransaction)
class SponsorPointsTransactionAdmin(admin.ModelAdmin):
    list_display = ("wallet", "tx_type", "amount", "reason", "created_by", "order", "created_at")
    list_filter = ("tx_type", "created_at")
    search_fields = ("wallet__driver__username", "wallet__sponsor__username", "reason")
    readonly_fields = ("created_at",)

@admin.register(BulkUploadLog)
class BulkUploadLogAdmin(admin.ModelAdmin):
    list_display = ("filename", "uploaded_by", "created_at", "total_rows", "created_count", "skipped_count", "success_rate_display")
    list_filter = ("created_at",)
    search_fields = ("filename", "uploaded_by__username")
    readonly_fields = ("uploaded_by", "filename", "total_rows", "created_count", "skipped_count", "error_count", "errors", "created_users", "skipped_users", "created_at")
    date_hierarchy = "created_at"
    
    @admin.display(description="Success Rate")
    def success_rate_display(self, obj):
        return f"{obj.success_rate}%"
    
    def has_add_permission(self, request):
        return False  # Prevent manual creation, only via upload