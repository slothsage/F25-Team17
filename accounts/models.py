from django.db import models
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