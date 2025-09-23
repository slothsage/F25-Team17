from django.contrib import admin
from .models import DriverProfile


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
	list_display = ("user", "phone", "address")
	search_fields = ("user__username", "user__email", "phone", "address")
