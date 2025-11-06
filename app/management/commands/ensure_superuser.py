from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.conf import settings
import os

User = get_user_model()

class Command(BaseCommand):
    help = "Create or update a Django superuser from env vars if not exists."

    def handle(self, *args, **options):
        username = os.getenv("ADMIN_USERNAME", "admin")
        email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        password = os.getenv("ADMIN_PASSWORD")

        if not password:
            self.stdout.write(self.style.WARNING("ADMIN_PASSWORD missing; skipping superuser creation."))
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_staff": True, "is_superuser": True, "is_active": True},
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"✅ Created superuser '{username}'"))
        else:
            # تأكيد الصلاحيات وتحديث كلمة المرور عند الحاجة
            updated = False
            if not user.is_superuser or not user.is_staff:
                user.is_superuser = True
                user.is_staff = True
                updated = True
            if password:
                user.set_password(password)
                updated = True
            if email and user.email != email:
                user.email = email
                updated = True
            if updated:
                user.save()
                self.stdout.write(self.style.SUCCESS(f"✅ Updated superuser '{username}'"))
            else:
                self.stdout.write(self.style.NOTICE(f"ℹ️ Superuser '{username}' already up-to-date"))
