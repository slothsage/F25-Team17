from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.validators import FileExtensionValidator # for validating uploaded file types
from django.contrib.auth.hashers import make_password, check_password
import os
import pyotp

def avatar_upload_path_to(instance, filename):
    base, ext = os.path.splitext(filename.lower())
    ext = ext if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"] else ".jpg"
    return f"avatars/user_{instance.user_id}{ext}"

class CustomLabel(models.Model):
    """Labels that admins can assign to users for organization or tracking"""
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(
        max_length=7,
        default="#007bff",
        help_text="Hex color code for label display (e.g. #ff0000)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Custom Label"
        verbose_name_plural = "Custom Labels"

    def __str__(self):
        return self.name

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
    is_locked = models.BooleanField(
        default=False,
        help_text="If checked, this user is prevented from logging in (admin only)",
        editable=False  
    )
    is_suspended = models.BooleanField(
        default=False,
        help_text="If checked, this user is temporarily suspended and cannot access any part of the system (admin only)",
        editable=False
    )

    # Admin-assigned user tags / labels
    labels = models.ManyToManyField(
        "CustomLabel",
        blank=True,
        related_name="drivers",
        help_text="Admin-assigned tags for categorizing users."
    )
    
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

# --- Security Questions --- 
class SecurityQuestion(models.Model):
    """Predefined set of security questions."""
    code = models.CharField(max_length=32, unique=True)
    text = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Security Question"
        verbose_name_plural = "Security Questions"

    def __str__(self):
        return self.text

class UserSecurityAnswer(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="security_answers")
    question = models.ForeignKey(SecurityQuestion, on_delete=models.CASCADE)
    # store hashed answer (never plaintext)
    answer_hash = models.CharField(max_length=255)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("user", "question")

    def set_answer(self, raw_answer: str):
        # normalize for case/whitespace; you can tune this policy
        normalized = " ".join((raw_answer or "").strip().lower().split())
        self.answer_hash = make_password(normalized)
        self.updated_at = timezone.now()

    def check_answer(self, raw_answer: str) -> bool:
        normalized = " ".join((raw_answer or "").strip().lower().split())
        return check_password(normalized, self.answer_hash)

    def __str__(self):
        return f"{self.user} - {self.question.code}"

# --- Alert Preferences --- 
class DriverNotificationPreference(models.Model):
    """Per-driver notification and UX preferences."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notif_prefs")

    # Kinds
    orders = models.BooleanField(default=True)
    points = models.BooleanField(default=True)
    promotions = models.BooleanField(default=False)

    # Delivery channels
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)

    # Visual theme
    THEME_CHOICES = [
        ("system", "System / Default"),
        ("light", "Light"),
        ("dark", "Dark"),
        ("contrast", "High Contrast"),
    ]
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default="system", help_text="Visual theme preference.")

    # Language
    LANGUAGE_CHOICES = [("en", "English"), ("es", "Español"), ("fr", "Français")]
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default="en")

    # Sounds
    SOUND_CHOICES = [("default", "Default chime"), ("silent", "Silent"), ("custom", "Custom file")]
    sound_mode = models.CharField(max_length=20, choices=SOUND_CHOICES, default="default")
    sound_file = models.FileField(
        upload_to="notif_sounds/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["mp3", "wav", "ogg"])],
    )

    # Low balance alert
    low_balance_alert_enabled = models.BooleanField(default=True)
    low_balance_threshold = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = "Driver Notification Preference"
        verbose_name_plural = "Driver Notification Preferences"

    def __str__(self):
        return f"NotifPrefs<{self.user}>"

    @classmethod
    def for_user(cls, user):
        """Get or create preferences for a user with sensible defaults."""
        obj, _ = cls.objects.get_or_create(
            user=user,
            defaults={
                "orders": True,
                "points": True,
                "promotions": False,
                "email_enabled": True,
                "sms_enabled": False,
                "sound_mode": "default",
                "low_balance_alert_enabled": True,
                "low_balance_threshold": 100,
            },
        )
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
    

class PointChangeLog(models.Model):
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="point_logs"
    )
    sponsor_name = models.CharField(max_length=120, blank=True)   
    sponsor_email = models.EmailField(blank=True)                 
    points_changed = models.IntegerField()
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.driver} {self.points_changed} pts @ {self.created_at:%Y-%m-%d}"

# --- Password Change Audit ---
class PasswordChangeLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_logs"
    )
    change_type = models.CharField(
        max_length=20, choices=[("manual", "Manual"), ("reset", "Reset by Admin")]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Password change for {self.user} ({self.change_type})"
    
# --- Driver Application Audit ---
class DriverApplicationLog(models.Model):
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sponsor_name = models.CharField(max_length=120, blank=True)   
    sponsor_email = models.EmailField(blank=True)                 
    status = models.CharField(
        choices=[("approved","Approved"),("rejected","Rejected")], max_length=20
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.driver} {self.status} @ {self.created_at:%Y-%m-%d}"

# --- Support Tickets ---
class SupportTicket(models.Model):
    """Driver support ticket for in-app help requests."""
    STATUS_CHOICES = [
        ("open", "Open"),
        ("resolved", "Resolved"),
    ]
    
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_tickets")
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets_resolved")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Support ticket"
        verbose_name_plural = "Support tickets"

    def __str__(self):
        return f"Ticket #{self.id} - {self.driver.username} - {self.subject} [{self.status}]"


class Complaint(models.Model):
    """Driver complaint submission and admin resolution system."""
    STATUS_CHOICES = [
        ("open", "Open"),
        ("resolved", "Resolved"),
    ]
    
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints")
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="complaints_resolved")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Complaint"
        verbose_name_plural = "Complaints"

    def __str__(self):
        return f"Complaint #{self.id} - {self.driver.username} - {self.subject} [{self.status}]"
    

class FailedLoginAttempt(models.Model):
    username = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} from {self.ip_address} at {self.timestamp}"
    
class DriverSettings(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="driver_settings")
    low_balance_alert_enabled = models.BooleanField(default=True)
    low_balance_threshold = models.PositiveIntegerField(default=100)

    def __str__(self):
        return f"{self.user.username} settings"
    
class UserMFA(models.Model):
    user = models.OneToOneField(
            settings.AUTH_USER_MODEL,
            on_delete=models.CASCADE,
            related_name="mfa",
    )
    mfa_enabled = models.BooleanField(default=False)
    mfa_totp_secret = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        help_text="Base32 secret for authenticator apps like Google Authenticator (TOTP)."
    )

    def get_totp(self):
        if not self.mfa_totp_secret:
            return None
        return pyotp.TOTP(self.mfa_totp_secret)
    
    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj
    
    def __str__(self):
        status = "ENABLED" if self.mfa_enabled else "DISABLED"
        return f"UserMFA<{self.user.username}> {status}"
    
# --- Sponsor applications / adoptions ---
class SponsorApplication(models.Model):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    STATUS_CHOICES = [
        (PENDING,  "Pending"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
    ]

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sponsor_applications",
    )
    sponsor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="driver_applications",
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("driver", "sponsor"),)
        indexes = [
            models.Index(fields=["sponsor", "status"]),
            models.Index(fields=["driver", "status"]),
        ]

    def __str__(self):
        return f"{self.driver} → {self.sponsor} ({self.status})"