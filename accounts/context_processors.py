from .models import (
    DriverNotificationPreference,
    Notification,
    MessageRecipient,
)
from django.utils import translation
from django.conf import settings

def theme(request):
    """
    Exposes 'theme' for all templates:
      'light' | 'dark' | 'contrast' | 'system'
    """
    val = "system"
    if request.user.is_authenticated:
        try:
            val = DriverNotificationPreference.for_user(request.user).theme or "system"
        except Exception:
            pass
    return {"theme": val}


def apply_user_language(get_response):
    def middleware(request):
        if request.user.is_authenticated:
            try:
                lang = request.user.notif_prefs.language
                translation.activate(lang)
                request.LANGUAGE_CODE = lang
            except Exception:
                pass
        return get_response(request)
    return middleware

def user_session_timeout(request):
    """Expose a per-user session timeout in seconds to templates.

    Priority:
      - If user is authenticated and has driver_profile.session_timeout_seconds set -> use it
      - Else: use settings.SESSION_COOKIE_AGE
    """
    default = getattr(settings, "SESSION_COOKIE_AGE", 5 * 60)
    try:
        if request.user.is_authenticated:
            profile = getattr(request.user, "driver_profile", None)
            if profile and getattr(profile, "session_timeout_seconds", None):
                return {"user_session_timeout": int(profile.session_timeout_seconds)}
    except Exception:
        pass
    return {"user_session_timeout": int(default)}

# Unread counters for notifications and messages
def unread_counts(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    try:
        return {
            "unread_notifications": Notification.objects.filter(user=request.user, read=False).count(),
            "unread_messages": MessageRecipient.objects.filter(user=request.user, is_read=False).count(),
        }
    except Exception:
        # Be resilient if tables are missing during migrations
        return {}


def impersonation_status(request):
    """Expose impersonation status to all templates for admin troubleshooting."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    
    impersonate_id = request.session.get('impersonate_id')
    impersonate_username = request.session.get('impersonate_username')
    
    if impersonate_id and impersonate_username:
        return {
            "is_impersonating": True,
            "original_admin_username": impersonate_username,
        }
    
    return {"is_impersonating": False}


def role_flags(request):
    """Expose simple role booleans for templates."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "is_sponsor": False,
            "is_driver": False,
            "is_admin": False,
        }

    is_sponsor = user.groups.filter(name="sponsor").exists()
    is_driver = hasattr(user, "driver_profile")
    is_admin = user.is_staff or user.is_superuser

    print(f"[DEBUG role_flags] user={request.user.username if request.user.is_authenticated else 'anon'}, "
        f"is_sponsor={request.user.groups.filter(name='sponsor').exists()}, "
        f"is_driver={hasattr(request.user, 'driver_profile')}, "
        f"is_admin={request.user.is_staff or request.user.is_superuser}")

    return {
        "is_sponsor": user.groups.filter(name="sponsor").exists(),
        "is_driver": hasattr(user, "driver_profile"),
        "is_admin": user.is_staff or user.is_superuser,
    }