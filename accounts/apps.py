from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    
    def ready(self):
        import accounts.signals
        from django.db.utils import OperationalError, ProgrammingError
        from .models import SecurityQuestion
        try:
            defaults = [
                ("pet_name", "What was the anme of your childhood pet?"),
                ("favorite_color", "What is your favorite color?"),
                ("high_school", "Where did you attend high school?"),
            ]
            for code, text in defaults:
                SecurityQuestion.objects.get_or_create(code=code, defaults={"text": text})
        except (OperationalError, ProgrammingError):
            pass