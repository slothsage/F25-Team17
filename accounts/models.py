from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.validators import FileExtensionValidator # for validating uploaded file types
import os

def avatar_upload_path_to(instance, filename):
    base, ext = os.path.splitext(filename.lower())
    ext = ext if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"] else ".jpg"
    return f"avatars/user_{instance.user_id}{ext}"

class DriverProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="driver_profile")
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=11, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to=avatar_upload_path_to,
        blank=True,
        null=True,
        default=None,   #"media/defaults/avatar.png",
        validators=[FileExtensionValidator(allowed_extensions=["jpg","jpeg","png","gif","webp"])],
    )
    
        # quick-contact fields (set by admin or seed data)
    sponsor_name  = models.CharField(max_length=120, blank=True)
    sponsor_email = models.EmailField(blank=True)

    # Optional per-user session timeout (seconds). If null, use system default in settings.SESSION_COOKIE_AGE
    session_timeout_seconds = models.PositiveIntegerField(null=True, blank=True, help_text="Per-user inactivity timeout in seconds (blank = use system default)")

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
    # delivery channels
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)

    SOUND_CHOICES = [
        ("default", "Default chime"),
        ("silent", "Silent"),
        ("custom", "Custom file"),
    ]
    sound_mode = models.CharField(max_length=20, choices=SOUND_CHOICES, default="default")
    sound_file = models.FileField(
        upload_to="notif_sounds/",
        blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["mp3", "wav", "ogg"])],
    )
    
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
    
class PointsLedger(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="points_ledger")
    delta = models.IntegerField()  # positive or negative
    reason = models.CharField(max_length=255, blank=True)
    balance_after = models.IntegerField()  
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.user} {sign}{self.delta} ({self.reason}) → {self.balance_after}"
    
# --- Announcement/Targeted Messaging ---
class Message(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_authored")
    subject = models.CharField(max_length=200)
    body = models.TextField()

    select_all = models.BooleanField(default=False)
    include_admins = models.BooleanField(default=False)
    include_sponsors = models.BooleanField(default=False)
    include_drivers = models.BooleanField(default=False)

    direct_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="messages_direct", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.created_at:%Y-%m-%d %H:%M})"
    
class MessageRecipient(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="recipients")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inbox_items")
    is_read = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(auto_now_add=True) #for ordering
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("message", "user"),)
        ordering = ["-delivered_at"]

    def __str__(self):
        return f"{self.user} - {self.message.subject}"


# --- Login Activity / Audit ---
class LoginActivity(models.Model):
    """Record user login attempts (success and failure) for admin audit.

    Stores a reference to the user when known (failed attempts may not have a user),
    timestamp, remote IP, user agent string, and a boolean `successful`.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="login_activities")
    username = models.CharField(max_length=150, blank=True, help_text="Username attempted (when user not resolved)")
    successful = models.BooleanField(default=False)
    ip_address = models.CharField(max_length=64, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Login activity"
        verbose_name_plural = "Login activities"

    def __str__(self):
        who = self.user.username if self.user else (self.username or "<unknown>")
        return f"LoginActivity<{who}> {'OK' if self.successful else 'FAIL'} @ {self.created_at:%Y-%m-%d %H:%M}"