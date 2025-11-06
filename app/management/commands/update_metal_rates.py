from django.core.management.base import BaseCommand
from django.conf import settings
from app.services import update_metals_assets_from_metalpriceapi

class Command(BaseCommand):
    help = "Fetch metal prices (gold/silver) from metalpriceapi and update metal assets (USD/gram)."

    def handle(self, *args, **options):
        api_key = 'd9aac6787678279fbb25f9098ab579cc'
        res = update_metals_assets_from_metalpriceapi(api_key=api_key)
        status = res.get("status")
        if status == "ok":
            self.stdout.write(self.style.SUCCESS("✅ Metal rates updated."))
        else:
            self.stdout.write(self.style.ERROR("❌ Metal update failed. See details below."))
        self.stdout.write(str(res))
