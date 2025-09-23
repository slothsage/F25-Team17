import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.core.cache import cache
from django.db.utils import ProgrammingError, OperationalError
from django.apps import apps

from .models import PasswordPolicy

# Allowed symbols
SYMBOLS = r"!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|`~"

DEFAULT_POLICY = {
    "min_length": 12,
    "require_upper": True,
    "require_lower": True,
    "require_digit": True,
    "require_symbol": True,
}

def _get_policy():
    # If app not ready or during migrate, be safe
    if not apps.is_installed("accounts"):
        return DEFAULT_POLICY

    key = "accounts.password_policy.current"
    cached = cache.get(key)
    if cached:
        return cached

    try:
        obj = PasswordPolicy.objects.order_by("-updated_at").first()
        if not obj:
            policy = DEFAULT_POLICY
        else:
            policy = {
                "min_length": obj.min_length,
                "require_upper": obj.require_upper,
                "require_lower": obj.require_lower,
                "require_digit": obj.require_digit,
                "require_symbol": obj.require_symbol,
            }
    except (ProgrammingError, OperationalError):
        # Table doesn't exist yet (e.g., during initial migrate)
        policy = DEFAULT_POLICY

    cache.set(key, policy, 60)
    return policy


class PolicyComplexityValidator:
    """
    Enforces the PasswordPolicy across registration, password change,
    and programmatic password sets (user.set_password()).
    """

    def validate(self, password, user=None):
        p = _get_policy()

        errors = []
        if len(password) < p["min_length"]:
            errors.append(_("Password must be at least %(n)d characters.") % {"n": p["min_length"]})
        if p["require_upper"] and not re.search(r"[A-Z]", password or ""):
            errors.append(_("Include at least one uppercase letter."))
        if p["require_lower"] and not re.search(r"[a-z]", password or ""):
            errors.append(_("Include at least one lowercase letter."))
        if p["require_digit"] and not re.search(r"\d", password or ""):
            errors.append(_("Include at least one number."))
        if p["require_symbol"] and not re.search(rf"[{re.escape(SYMBOLS)}]", password or ""):
            errors.append(_("Include at least one symbol."))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        p = _get_policy()
        parts = [_(f"at least {p['min_length']} characters")]
        if p["require_upper"]: parts.append(_("an uppercase letter"))
        if p["require_lower"]: parts.append(_("a lowercase letter"))
        if p["require_digit"]: parts.append(_("a number"))
        if p["require_symbol"]: parts.append(_("a symbol"))
        return _("Your password must include ") + ", ".join(parts) + "."