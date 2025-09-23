from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache

from accounts.models import PasswordPolicy

# Create your tests here.

PASSWORD_VALIDATORS_FOR_TESTS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "accounts.validators.PolicyComplexityValidator"},
]

@override_settings(AUTH_PASSWORD_VALIDATORS=PASSWORD_VALIDATORS_FOR_TESTS)
class PasswordPolicyValidatorTests(TestCase):
    def setUp(self):
        cache.clear()
        PasswordPolicy.objects.create(
            min_length=12,
            require_upper=True,
            require_lower=True,
            require_digit=True,
            require_symbol=True,
            expiry_days=0,
        )
        cache.delete("accounts.password_policy.current")

    def test_weak_password_rejected(self):
        with self.assertRaises(ValidationError):
            validate_password("abc")

    def test_missing_uppercase_rejected(self):
        with self.assertRaises(ValidationError):
            validate_password("goodpassw0rd!")

    def test_missing_lowercase_rejected(self):
        with self.assertRaises(ValidationError):
            validate_password("GOODPASSW0RD!")

    def test_missing_digit_rejected(self):
        with self.assertRaises(ValidationError):
            validate_password("GoodPassword!")

    def test_missing_symbol_rejected(self):
        with self.assertRaises(ValidationError):
            validate_password("GoodPassw0rd")

    def test_strong_password_accepted(self):
        validate_password("GoodPassw0rd!")

    def test_policy_change_takes_effect_without_symbol(self):
        # Fails first (symbol required)
        with self.assertRaises(ValidationError):
            validate_password("GoodPassw0rd")

        # Loosen policy
        p = PasswordPolicy.objects.order_by("-updated_at").first()
        assert p is not None
        p.require_symbol = False
        p.save()
        cache.delete("accounts.password_policy.current")

        # Now passes
        validate_password("GoodPassw0rd")

    def test_min_length_enforced(self):
        p = PasswordPolicy.objects.order_by("-updated_at").first()
        assert p is not None
        p.min_length = 16
        p.save()
        cache.delete("accounts.password_policy.current")

        with self.assertRaises(ValidationError):
            validate_password("GoodPassw0rd!")  # ~13 chars

        validate_password("GoodPassword0000!")  # >=16 and complex