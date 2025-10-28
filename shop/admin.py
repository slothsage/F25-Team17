from django.contrib import admin
from .models import PointsConfig

# Register your models here.

@admin.register(PointsConfig)
class PointsConfigAdmin(admin.ModelAdmin):
    list_display = ("points_per_usd", "updated_at")

    def has_add_permission(self, request):
        return not PointsConfig.objects.exists()