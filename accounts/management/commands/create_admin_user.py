from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Create a superuser (admin) non-interactively: provide --username, --email, --password'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True, help='Username for the superuser')
        parser.add_argument('--email', required=True, help='Email address for the superuser')
        parser.add_argument('--password', required=True, help='Password for the superuser')

    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username']
        email = options['email']
        password = options['password']

        if User.objects.filter(username=username).exists():
            raise CommandError(f"User with username '{username}' already exists")

        user = User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created."))
