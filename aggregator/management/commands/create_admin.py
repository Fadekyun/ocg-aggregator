from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update a Django superuser from command arguments"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument("--email", default="")

    def handle(self, *args, **options):
        User = get_user_model()
        user, _ = User.objects.update_or_create(
            username=options["username"],
            defaults={"email": options["email"], "is_staff": True, "is_superuser": True},
        )
        user.set_password(options["password"])
        user.save()
        self.stdout.write(self.style.SUCCESS(f"admin ready: {user.username}"))

