from django.urls import reverse
from django.core.mail import send_mail
from django.conf import settings
from .models import DriverNotificationPreference, Notification


def _kind_allowed(user, kind: str) -> bool:
    """
    Gate by per-kind preferences; 'dropped' bypasses mutes.
    """
    if kind == "dropped":
        return True
    prefs = DriverNotificationPreference.for_user(user)
    return {
        "orders": prefs.orders,
        "points": prefs.points,
        "promotions": prefs.promotions,
    }.get(kind, True)


def _send_sms_safe(user, title: str, body: str, url: str = "") -> bool:
    """
    Optional SMS hook. Returns True if an SMS was (or would be) sent, False otherwise.
    Implement with Twilio/etc. later. For now we no-op if no phone or no provider.
    """
    # Try to find a phone number
    phone = ""
    try:
        # DriverProfile has `phone`
        if hasattr(user, "driver_profile") and user.driver_profile and user.driver_profile.phone:
            phone = user.driver_profile.phone
    except Exception:
        pass

    if not phone:
        return False

    # TODO: integrate real SMS provider here.
    # Example (pseudo):
    # twilio_client.messages.create(
    #     to=phone,
    #     from_=settings.TWILIO_FROM_NUMBER,
    #     body=f"{title}: {body} {(' ' + url) if url else ''}".strip(),
    # )
    return False  # change to True once wired up


def _notify_channels(user, kind: str, title: str, body: str, url: str = ""):
    """
    Channel fan-out with duplicate protection:
      - Always create in-app Notification if kind allowed.
      - If SMS enabled -> try SMS (and SKIP email to avoid duplicates).
      - Else if Email enabled -> send email (if user.email).
    """
    if _kind_allowed(user, kind):
        Notification.objects.create(user=user, kind=kind, title=title, body=body, url=url)

    # Channel prefs
    prefs = DriverNotificationPreference.for_user(user)

    if prefs.sms_enabled:
        sent_sms = _send_sms_safe(user, title, body, url)
        if sent_sms:
            return  # do not double-send email


    if prefs.email_enabled and getattr(user, "email", ""):
        try:
            send_mail(
                subject=title,
                message=f"{body}\n\n{('View: ' + url) if url else ''}".strip(),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            pass

def send_in_app_notification(user, kind: str, title: str, body: str, url: str = ""):
    """
    kind: 'orders' | 'points' | 'promotions' | 'dropped'
    - 'dropped' ALWAYS bypasses prefs (cannot be muted)
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
            return  

    Notification.objects.create(
        user=user,
        kind=kind,
        title=title,
        body=body,
        url=url,
    )


def on_points_updated(user, delta: int, reason: str, new_balance: int):
    """
    Emits an in-app notification (respects prefs) and optionally an email.
    """
    title = "Points updated"
    sign = "+" if delta >= 0 else ""
    body = f"{sign}{delta} — {reason}. New balance: {new_balance}"
    # Use the namespaced URL
    url = reverse("accounts:points_history")

    # In-app 
    send_in_app_notification(user, "points", title, body, url=url)

    # Optional email 
    if getattr(user, "email", ""):
        try:
            send_mail(
                subject=title,
                message=f"{body}\n\nView history: {url}",
                from_email=None,  # DEFAULT_FROM_EMAIL
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            pass

def on_order_delayed(order):
    """
    Send an 'Order Delayed' in-app notification to the driver.
    Respects the 'orders' preference.
    De-duplicates by URL+title so we don't spam.
    """
    user = order.driver
    try:
        url = reverse("order_detail", args=[order.id])
    except Exception:
        url = ""

    title = "Order Delayed"
    body = f"Order #{order.id} is delayed. We’ll notify you when it ships."

    #  if we've already sent one for this order+url, skip
    if Notification.objects.filter(
        user=user, kind="orders", url=url, title=title
    ).exists():
        return

    # respect prefs via your existing helper
    send_in_app_notification(user, "orders", title, body, url=url)