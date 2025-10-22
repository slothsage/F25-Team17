from django.core.cache import cache
from .models import PasswordPolicy

def ensure_default_policy(**kwargs):
    PasswordPolicy.objects.get_or_create(
        id=1,
        defaults=dict(min_length=12, require_upper=True, require_lower=True, require_digit=True, require_symbol=True, expiry_days=0),
    )
    cache.delete("accounts.password_policy.current")