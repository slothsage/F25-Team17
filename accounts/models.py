from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.validators import FileExtensionValidator # for validating uploaded file types
from django.contrib.auth.hashers import make_password, check_password
import os
import pyotp
from django.core.exceptions import ValidationError


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
    sponsors = models.ManyToManyField(User, related_name="sponsored_drivers", blank=True)
    sponsor_name  = models.CharField(max_length=120, blank=True)
    sponsor_email = models.EmailField(blank=True)

    # Optional per-user session timeout (seconds). If null, use system default in settings.SESSION_COOKIE_AGE
    session_timeout_seconds = models.PositiveIntegerField(null=True, blank=True, help_text="Per-user inactivity timeout in seconds (blank = use system default)")
    is_locked = models.BooleanField(
        default=False,
        help_text="If checked, this user is prevented from logging in (admin only)",
        editable=False  
    )
    
    # Points goal for progress tracking
    points_goal = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Personal points goal for progress tracking"
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

class SponsorProfile(models.Model):
    """Profile for sponsor users to store sponsor-specific data."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="sponsor_profile")
    is_archived = models.BooleanField(
        default=False,
        help_text="If checked, this sponsor is archived and won't appear in regular searches"
    )
    archived_at = models.DateTimeField(null=True, blank=True, help_text="When the sponsor was archived")
    archived_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_sponsors",
        help_text="Admin who archived this sponsor"
    )
    points_per_usd = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Points per USD for this sponsor (if not set, uses global default)"
    )
    
    def __str__(self):
        return f"SponsorProfile<{self.user.username}>"
    
    def get_points_per_usd(self):
        """Get the points per USD for this sponsor, or return global default."""
        if self.points_per_usd is not None:
            return self.points_per_usd
        from shop.models import PointsConfig
        return PointsConfig.get_solo().points_per_usd

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
    
# --- x Sponsor points ---
# --- Per-sponsor points ---
class SponsorPointsAccount(models.Model):
    driver  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="points_accounts")
    sponsor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="issued_points_accounts")
    balance = models.IntegerField(default=0)
    is_primary = models.BooleanField(default=False)  # only true for one at a time

    class Meta:
        unique_together = (("driver", "sponsor"),)
        indexes = [
            models.Index(fields=["driver"]),
            models.Index(fields=["sponsor"]),
        ]

    def __str__(self):
        return f"{self.driver.username} ↔ {self.sponsor.username} : {self.balance} pts"

    def set_primary(self):
        # ensure uniqueness across this driver
        SponsorPointsAccount.objects.filter(driver=self.driver, is_primary=True).exclude(pk=self.pk).update(is_primary=False)
        if not self.is_primary:
            self.is_primary = True
            self.save(update_fields=["is_primary"])

    def apply_points(self, delta: int, *, reason: str = "", awarded_by=None):
        """Add (or subtract) points and log the transaction."""
        self.balance = (self.balance or 0) + int(delta)
        self.save(update_fields=["balance"])
        SponsorPointsTransaction.objects.create(
            account=self, delta=int(delta), reason=reason or "", awarded_by=awarded_by
        )

class SponsorPointsTransaction(models.Model):
    account = models.ForeignKey(SponsorPointsAccount, on_delete=models.CASCADE, related_name="transactions")
    delta = models.IntegerField()  # + or -
    reason = models.CharField(max_length=255, blank=True)
    awarded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="points_awards")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.account.driver} {sign}{self.delta} ({self.reason}) by {self.awarded_by or 'system'}"


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
    

class ChatRoom(models.Model):
    """
    Chat room linking a sponsor with their drivers.
    Each sponsor has one chat room that includes all their assigned drivers.
    """
    sponsor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sponsor_chat_rooms",
        limit_choices_to={"groups__name": "sponsor"}
    )
    name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Chat Room"
        verbose_name_plural = "Chat Rooms"
    
    def __str__(self):
        return self.name or f"Chat with {self.sponsor.username}"
    
    def get_participants(self):
        """Get all participants in this chat room (sponsor + all drivers)"""
        drivers = User.objects.filter(
            driver_profile__sponsor_name=self.sponsor.username
        )
        return list(drivers) + [self.sponsor]
    
    def get_latest_message(self):
        """Get the most recent message in this chat room"""
        return self.messages.order_by("-created_at").first()
    
    def get_unread_count(self, user):
        """Get count of unread messages for a specific user"""
        return self.messages.exclude(sender=user).filter(read_by__user=user, read_by__is_read=False).count()


class ChatMessage(models.Model):
    """
    Individual message in a chat room.
    """
    chat_room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name="messages"
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_messages"
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ["created_at"]
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"
    
    def __str__(self):
        return f"{self.sender.username}: {self.message[:50]}"
    
    def mark_as_read(self, user):
        """Mark this message as read by a specific user"""
        MessageReadStatus.objects.update_or_create(
            message=self,
            user=user,
            defaults={"is_read": True, "read_at": timezone.now()}
        )


class MessageReadStatus(models.Model):
    """
    Track which users have read which messages.
    """
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="read_by"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="message_read_statuses"
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ["message", "user"]
        verbose_name = "Message Read Status"
        verbose_name_plural = "Message Read Statuses"
    
    def __str__(self):
        status = "Read" if self.is_read else "Unread"
        return f"{self.user.username} - {status}"
    

# --- Sponsor applications / adoptions ---
class SponsorshipRequest(models.Model):
    REQUEST_TYPES = [
        ("driver_to_sponsor", "Driver → Sponsor"),
        ("sponsor_to_driver", "Sponsor → Driver"),
    ]
    from_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_sponsorship_requests"
    )
    to_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_sponsorship_requests"
    )
    request_type = models.CharField(
        max_length=20,
        choices=REQUEST_TYPES,
        default="driver_to_sponsor",
        help_text="Indicates who initiated the request"
    )
    message = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("denied", "Denied"),
            ("ended", "Ended"),
        ],
    default="pending"
)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def approve(self):
        self.status = "approved"
        self.reviewed_at = timezone.now()
        self.save()
        # Identify which side is the driver vs sponsor
        driver = self.to_user if hasattr(self.to_user, "driver_profile") else self.from_user
        sponsor = self.from_user if self.from_user.groups.filter(name="sponsor").exists() else self.to_user
        # Add sponsor to the driver's profile
        driver.driver_profile.sponsors.add(sponsor)
        driver.driver_profile.save()

    def deny(self):
        self.status = "denied"
        self.reviewed_at = timezone.now()
        self.save()

    def end(self, ended_by):
        """End an approved sponsorship relationship (either side)."""
        if self.status != "approved":
            return  # only active sponsorships can be ended

        # Mark as ended (new status type)
        self.status = "ended"
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_at"])

        # Remove sponsor from driver profile if exists
        driver = self.to_user if hasattr(self.to_user, "driver_profile") else self.from_user
        sponsor = self.from_user if self.from_user.groups.filter(name="sponsor").exists() else self.to_user
        if hasattr(driver, "driver_profile"):
            driver.driver_profile.sponsors.remove(sponsor)
            driver.driver_profile.save()

        # Notify both users
        from .models import Notification  # local import to avoid circular dependency
        Notification.objects.create(
            user=driver,
            kind="system",
            title="Sponsorship Ended",
            body=f"Your sponsorship with {sponsor.username} has been ended by {ended_by.username}.",
            )
        Notification.objects.create(
            user=sponsor,
            kind="system",
            title="Sponsorship Ended",
            body=f"Your sponsorship with {driver.username} has been ended by {ended_by.username}.",
        )

    def __str__(self):
        return f"{self.from_user.username} → {self.to_user.username} ({self.status})"


class SponsorPointsAccount(models.Model):
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sponsor_wallets")
    sponsor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="issued_wallets")  # your Sponsor user/account
    balance = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("driver", "sponsor"),)

    def __str__(self):
        return f"{self.driver} @ {self.sponsor} → {self.balance} pts{' (primary)' if self.is_primary else ''}"

    @transaction.atomic
    def set_primary(self):
        SponsorPointsAccount.objects.filter(driver=self.driver, is_primary=True).update(is_primary=False)
        self.is_primary = True
        self.save(update_fields=["is_primary", "updated_at"])

    @transaction.atomic
    def apply_points(self, delta, *, reason="", created_by=None, order=None):
        # Negative deltas spend points; don’t allow negative balances.
        if delta == 0:
            return
        
        new_bal = self.balance + delta
        if new_bal < 0:
            raise ValidationError("Insufficient points in this sponsor wallet.")
        SponsorPointsTransaction.objects.create(
            wallet=self,
            tx_type="credit" if delta > 0 else "debit",
            amount=abs(delta),
            created_by=created_by,
            order=order,
            reason=reason[:255] if hasattr(SponsorPointsTransaction, "reason") else None,
        )
        # update balance
        self.balance = new_bal
        self.save(update_fields=["balance", "updated_at"])

        # log to the consolidated ledger for driver history displays
        prior_total = (
            PointsLedger.objects.filter(user=self.driver)
            .aggregate(total=Sum("delta"))
            .get("total") or 0
        )
        ledger_reason = reason or (
            f"{'Awarded' if delta > 0 else 'Spent'} via {self.sponsor.get_full_name() or self.sponsor.username}"
        )
        new_balance = prior_total + delta
        PointsLedger.objects.create(
            user=self.driver,
            delta=delta,
            reason=ledger_reason[:255],
            balance_after=new_balance,
        )
        
        # Trigger notification for points update
        try:
            from .notifications import on_points_updated
            on_points_updated(self.driver, delta, ledger_reason[:255], new_balance)
        except Exception as e:
            # Log error but don't fail the transaction
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to send points notification: {e}", exc_info=True)

class SponsorPointsTransaction(models.Model):
    wallet = models.ForeignKey(SponsorPointsAccount, on_delete=models.CASCADE, related_name="transactions")
    tx_type = models.CharField(max_length=10, choices=[("credit","credit"),("debit","debit")])
    amount = models.PositiveIntegerField()
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    order = models.ForeignKey("shop.Order", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tx_type} {self.amount} to {self.wallet}"