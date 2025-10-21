from urllib import request
from .models import DriverNotificationPreference
from .models import Notification, MessageRecipient
from django.utils import translation

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

#trying to include an unread and read counts for notifications and messages
def unread_counts(requests):
    if not requests.user.is_authenticated:
        return {}
    return {
        "unread_notifications": Notification.objects.filter(user=request.user, read=False).count(),
        "unread_messages": MessageRecipient.objects.filter(user=request.user, is_read=False).count(),
    }