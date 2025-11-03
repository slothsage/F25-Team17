from django.core.cache import cache
from .models import PasswordPolicy, PointsLedger, PointChangeLog, DriverProfile, LoginActivity, PasswordChangeLog
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.utils import timezone
from .models import LoginActivity
from django.db.models.signals import post_save
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save, post_migrate

User = get_user_model()

def ensure_default_policy(**kwargs):
    PasswordPolicy.objects.get_or_create(
        id=1,
        defaults=dict(min_length=12, require_upper=True, require_lower=True, require_digit=True, require_symbol=True, expiry_days=0),
    )
    cache.delete("accounts.password_policy.current")

@receiver(post_migrate)
def ensure_policy_after_migrate(sender, **kwargs):
    if getattr(sender, "name", "") == "accounts":
        ensure_default_policy()

# Record successful logins
@receiver(user_logged_in)
def record_successful_login(sender, request, user, **kwargs):
    try:
        ip = request.META.get("REMOTE_ADDR", "")
        ua = request.META.get("HTTP_USER_AGENT", "")
    except Exception:
        ip = ""
        ua = ""
    LoginActivity.objects.create(user=user, username=user.get_username(), successful=True, ip_address=ip, user_agent=ua)


# Record failed login attempts
@receiver(user_login_failed)
def record_failed_login(sender, credentials, request, **kwargs):
    # credentials may contain 'username' or 'email' depending on auth backend
    username = credentials.get("username") if isinstance(credentials, dict) else ""
    try:
        ip = request.META.get("REMOTE_ADDR", "") if request is not None else ""
        ua = request.META.get("HTTP_USER_AGENT", "") if request is not None else ""
    except Exception:
        ip = ""
        ua = ""
    LoginActivity.objects.create(user=None, username=username or "", successful=False, ip_address=ip, user_agent=ua)

# --- Points -> PointChangeLog ---

@receiver(post_save, sender=PointsLedger)
def log_point_change(sender, instance: PointsLedger, created, **kwargs):
    if not created:
        return
    user = instance.user
    sponsor_name = ""
    sponsor_email = ""
    try:
        if hasattr(user, "driver_profile") and user.driver_profile:
            sponsor_name = user.driver_profile.sponsor_name or ""
            sponsor_email = user.driver_profile.sponsor_email or ""
    except Exception:
        pass

    PointChangeLog.objects.create(
        driver=user,
        sponsor_name=sponsor_name,
        sponsor_email=sponsor_email,
        points_changed=instance.delta,
        reason=instance.reason or "",
    )


# --- Password change audit ---

@receiver(pre_save, sender=User)
def log_password_change(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    if old.password != instance.password:
        PasswordChangeLog.objects.create(
            user=instance,
            change_type="manual",
        )