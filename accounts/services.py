from django.db import transaction
from django.db.models import Sum
from .models import PointsLedger
from .notifications import on_points_updated

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