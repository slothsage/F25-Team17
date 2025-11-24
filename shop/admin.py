from django.contrib import admin
from .models import SponsorCatalogItem, DriverCatalogItem, Order
from .models import PointsConfig

# Register your models here.

@admin.register(PointsConfig)
class PointsConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "points_per_usd", "points_expiry_days_display", "updated_at")
    fields = ("points_per_usd", "points_expiry_days", "updated_at")
    readonly_fields = ("updated_at",)
    list_display_links = ("__str__", "points_per_usd")  # Make both clickable
    
    def points_expiry_days_display(self, obj):
        if obj.points_expiry_days == 0:
            return "Never expires"
        return f"{obj.points_expiry_days} days"
    points_expiry_days_display.short_description = "Points Expiry"

    def has_add_permission(self, request):
        return not PointsConfig.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of the singleton
        return False


@admin.register(SponsorCatalogItem)
class SponsorCatalogItemAdmin(admin.ModelAdmin):
    list_display = ("name", "sponsor", "points_cost", "price_usd", "category", "is_active", "created_at")
    list_filter = ("is_active", "category", "created_at")
    search_fields = ("name", "description", "sponsor__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DriverCatalogItem)
class DriverCatalogItemAdmin(admin.ModelAdmin):
    list_display = ("name", "points_cost", "price_usd", "category", "is_active", "added_by", "created_at")
    list_filter = ("is_active", "category", "created_at")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "driver", "sponsor_name", "status", "tracking_number", "points_spent", "placed_at")
    list_filter = ("status", "placed_at", "sponsor_name")
    search_fields = ("id", "driver__username", "sponsor_name", "tracking_number")
    readonly_fields = ("placed_at", "updated_at")
    fieldsets = (
        ("Order Information", {
            "fields": ("driver", "sponsor_name", "status", "points_spent", "placed_at", "updated_at")
        }),
        ("Shipping Information", {
            "fields": ("tracking_number", "ship_name", "ship_line1", "ship_line2", "ship_city", "ship_state", "ship_postal", "ship_country", "expected_delivery_date")
        }),
    )
    list_editable = ("status", "tracking_number")