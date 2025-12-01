from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from .models import PointsConfig, POINTS_CACHE_KEY

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

def get_points_per_usd(user=None):
    if user is not None:
        try:
            from accounts.models import SponsorProfile  # local import to avoid circulars
            # Only sponsors will actually have a SponsorProfile; others will drop through
            profile = SponsorProfile.objects.filter(user=user).first()
            if profile and profile.points_per_usd is not None:
                return profile.points_per_usd
        except Exception:
            # During migrations or if accounts isn't ready, just fall back to global
            pass

    # Global default path (same as before, using cache)
    val = cache.get(POINTS_CACHE_KEY)
    if val is not None:
        return val
    val = PointsConfig.get_solo().points_per_usd
    cache.set(POINTS_CACHE_KEY, val, 300)  # 5 minutes
    return val

def get_points_per_usd_for_sponsor(sponsor_user):
    """
    Return the points-per-USD ratio for a specific sponsor user.
    Falls back to the global default if they don't have a profile or
    have not set a custom ratio.
    """
    from accounts.models import SponsorProfile  # local import to avoid circular

    try:
        profile = sponsor_user.sponsor_profile
    except SponsorProfile.DoesNotExist:
        return get_points_per_usd()

    # SponsorProfile already has get_points_per_usd() that falls back
    # to the global PointsConfig if the field is blank.
    return profile.get_points_per_usd()