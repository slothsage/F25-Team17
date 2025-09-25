from .models import DriverNotificationPreference, Notification

def send_in_app_notification(user, kind: str, title: str, body: str, url: str = ""):
    """
    kind: "orders" | "points" | "promotions" | "dropped"
    - "dropped" ALWAYS bypasses prefs (cannot be muted)
    - others respect DriverNotificationPreference
    """
    if kind != "dropped":
        prefs = DriverNotificationPreference.for_user(user)
        allowed = {
            "orders": prefs.orders,
            "points": prefs.points,
            "promotions": prefs.promotions,
        }.get(kind, True)
        if not allowed:
            return  # muted by user preference


    try:
        from .models import Notification  
        Notification.objects.create(user=user, kind=kind, title=title, body=body, url=url)
    except Exception:
        # safe no-op if Notification model doesn't exist yet
        pass

def send_in_app_notification(user, kind: str, title: str, body: str, url: str = ""):
    """
    kind: 'orders' | 'points' | 'promotions' | 'dropped'
    'dropped' bypasses user prefs.
    """
    if kind != "dropped":
        prefs = DriverNotificationPreference.for_user(user)
        allowed = {
            "orders": prefs.orders,
            "points": prefs.points,
            "promotions": prefs.promotions,
        }.get(kind, True)
        if not allowed:
            return

    Notification.objects.create(
        user=user,
        kind=kind,
        title=title,
        body=body,
        url=url,
    )