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
