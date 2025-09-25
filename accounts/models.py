from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User

class DriverProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="driver_profile")
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"DriverProfile<{self.user.username}>"
    

class PasswordPolicy(models.Model):
    min_length = models.PositiveIntegerField(default=12)
    require_upper = models.BooleanField(default=True)
    require_lower = models.BooleanField(default=True)
    require_digit = models.BooleanField(default=True)
    require_symbol = models.BooleanField(default=True)
    expiry_days = models.PositiveIntegerField(default=0, help_text="0 = never expires")

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Password Policy (updated {self.updated_at:%Y-%m-%d %H:%M})"

    class Meta:
        verbose_name = "Password policy"
        verbose_name_plural = "Password policies"

# --- Alert Preferences --- 
class DriverNotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notif_prefs")
 
    orders = models.BooleanField(default=True)
    points = models.BooleanField(default=True)
    promotions = models.BooleanField(default=False) 

    class Meta:
        verbose_name = "Driver Notification Preference"
        verbose_name_plural = "Driver Notification Preferences"

    def __str__(self):
        return f"NotifPrefs<{self.user}>"

    @classmethod
    def for_user(cls, user):
        # create with defaults if missing
        obj, _ = cls.objects.get_or_create(user=user, defaults={"orders": True, "points": True, "promotions": False})
        return obj
    
class Notification(models.Model):
    KIND_CHOICES = [
        ("orders", "Orders"),
        ("points", "Points"),
        ("promotions", "Promotions"),
        ("dropped", "Dropped"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    title = models.CharField(max_length=200)
    body = models.TextField()
    url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.kind}] {self.title} → {self.user}"