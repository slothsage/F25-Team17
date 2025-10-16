from .models import DriverNotificationPreference

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