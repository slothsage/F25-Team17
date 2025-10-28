from django.core.cache import cache
from .models import PasswordPolicy
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver
from django.utils import timezone
from .models import LoginActivity



def ensure_default_policy(**kwargs):
    PasswordPolicy.objects.get_or_create(
        id=1,
        defaults=dict(min_length=12, require_upper=True, require_lower=True, require_digit=True, require_symbol=True, expiry_days=0),
    )
    cache.delete("accounts.password_policy.current")


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