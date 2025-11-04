from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    
    def ready(self):
        import accounts.signals
        from django.db.models.signals import post_migrate
        from django.dispatch import receiver
        from .models import SecurityQuestion

        @receiver(post_migrate)
        def create_default_security_questions(sender, **kwargs):
            """Safely create predefined security questions after migrations."""
            defaults = [
                ("pet_name", "What was the name of your childhood pet?"),
                ("favorite_color", "What is your favorite color?"),
                ("high_school", "Where did you attend high school?"),
            ]
            for code, text in defaults:
                SecurityQuestion.objects.get_or_create(code=code, defaults={"text": text})