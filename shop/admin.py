from django.contrib import admin
from .models import SponsorCatalogItem, DriverCatalogItem
from .models import PointsConfig

# Register your models here.

@admin.register(PointsConfig)
class PointsConfigAdmin(admin.ModelAdmin):
    list_display = ("points_per_usd", "updated_at")

    def has_add_permission(self, request):
        return not PointsConfig.objects.exists()


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