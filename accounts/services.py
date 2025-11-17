from django.db import transaction
from django.db.models import Sum
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from .models import PointsLedger, SponsorPointsAccount
from .notifications import on_points_updated
import logging
log = logging.getLogger(__name__)

@transaction.atomic
def adjust_points(user, delta: int, reason: str = "") -> PointsLedger:
    # current balance before adjustment
    total = PointsLedger.objects.filter(user=user).aggregate(s=Sum("delta"))["s"] or 0
    new_balance = total + delta

    # create ledger entry
    entry = PointsLedger.objects.create(
        user=user,
        delta=delta,
        reason=reason,
        balance_after=new_balance,
    )

    # triggers the notification 
    on_points_updated(user, delta, reason or "Adjustment", new_balance)

    return entry


def get_driver_points_balance(user):
    """
    Return the driver's aggregated balance across all sponsor wallets.
    """
    if not user:
        return 0

    return (
        SponsorPointsAccount.objects
        .filter(driver=user)
        .aggregate(total=Sum("balance"))
        .get("total") or 0
    )

def notify_password_change(user):
    """
    Security notifcation of when a password changes
    """
    when = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S %Z")
    subject = "Your password was reset"
    body = (
        f"Hello {user.get_username()},\n\n"
        f"This is a security notification to alert you of a password change on {when}.\n"
        f"If this was not you, please reset your password immediately and contact support.\n\n"
        f"— {getattr(settings, 'PROJECT_NAME', 'Support Team')}"
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")
    recipient_list = [user.email] if user.email else []

    if recipient_list:
        try:
            send_mail(subject, body, from_email, recipient_list, fail_silently=False)  # turn off silence while debugging
            log.info("Password-change email sent to %s", recipient_list[0])
        except Exception as e:
            log.exception("Failed to send password-change email: %s", e)
    else:
        log.warning("No email on user %r; skipping password-change notification", user)