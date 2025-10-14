from django.conf import settings


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
