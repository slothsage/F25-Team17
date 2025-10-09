from datetime import timedelta
from django.utils import timezone

PENDING_STATUSES = {"new", "placed", "processing", "packed", "shipped"}  
TERMINAL_STATUSES = {"delivered", "cancelled"}

def _first_existing_attr(obj, names):
    for n in names:
        if hasattr(obj, n) and getattr(obj, n) is not None:
            return getattr(obj, n)
    return None

def order_is_delayed(order, now=None, grace_hours=24):
    """
    Heuristic: an order is delayed if it's not in a terminal state and
    'now' is past the promised ship-by (or fallback) plus a grace period.
    """
    now = now or timezone.now()

    # quick exit if delivered/cancelled
    status = getattr(order, "status", None)
    if status and status.lower() in TERMINAL_STATUSES:
        return False

    # choose a promised deadline from common field names, else fallback
    promised = _first_existing_attr(order, [
        "expected_ship_by",      # DateTimeField
        "expected_ship_end",     # DateTimeField
        "ship_by",               # Date/DateTime
        "promised_ship_by",      # DateTime
    ])

    if promised is None:
        # fallback: 7 days from placed_at
        placed_at = getattr(order, "placed_at", None) or now
        promised = placed_at + timedelta(days=7)

    # grace
    deadline = promised + timedelta(hours=grace_hours)
    return now > deadline