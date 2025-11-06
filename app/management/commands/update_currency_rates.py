from django.core.management.base import BaseCommand
from app.services import update_currency_assets_from_erapi

class Command(BaseCommand):
    help = "Fetch FX rates from ER-API and update Money assets (unit_price_usd)."

    def handle(self, *args, **options):
        res = update_currency_assets_from_erapi()
        status = res.get("status")
        if status == "ok":
            self.stdout.write(self.style.SUCCESS("✅ Currency rates updated."))
        else:
            self.stdout.write(self.style.ERROR("❌ Currency update failed. See details below."))
        self.stdout.write(str(res))
