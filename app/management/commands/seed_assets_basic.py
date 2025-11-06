# app/management/commands/seed_assets_basic.py
from django.core.management.base import BaseCommand
from decimal import Decimal
from app.models import Asset


class Command(BaseCommand):
    help = "Seed the Asset table with gold (19k, 21k, 24k), silver, and major currencies including Middle East and Asia."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding assets with codes..."))

        # ----------------------------
        # أسعار المعادن (تقريبية بالدولار لكل غرام)
        # ----------------------------
        gold_24_usd = Decimal("75.0")
        gold_21_usd = (gold_24_usd * Decimal("21") / Decimal("24")).quantize(Decimal("0.000001"))
        gold_19_usd = (gold_24_usd * Decimal("19") / Decimal("24")).quantize(Decimal("0.000001"))
        silver_usd = Decimal("0.95")

        metals = [
            # asset_code , name  , asset_type , unit_name , nationality , price
            ("GOLD_24", "Gold", "24", "gram", "", gold_24_usd),
            ("GOLD_21", "Gold", "21", "gram", "", gold_21_usd),
            ("GOLD_19", "Gold", "19", "gram", "", gold_19_usd),
            ("SILVER",  "Silver","فضة","gram", "", silver_usd),
        ]

        # ----------------------------
        # العملات (Asset Type = الاسم العربي للعملة) — الأسعار كما هي
        # ----------------------------
        currencies = [
            # code , name   , asset_type(AR)         , unit_name , country             , price (USD per 1 unit)
            ("USD", "Money", "دولار",                 "amount",   "United States",       Decimal("1.0")),
            ("EUR", "Money", "يورو",                  "amount",   "European Union",      Decimal("1.08")),
            ("GBP", "Money", "جنيه إسترليني",        "amount",   "United Kingdom",      Decimal("1.27")),
            ("CHF", "Money", "فرنك سويسري",          "amount",   "Switzerland",         Decimal("1.11")),
            ("JPY", "Money", "ين ياباني",             "amount",   "Japan",               Decimal("0.0067")),
            ("CNY", "Money", "يوان صيني",            "amount",   "China",               Decimal("0.14")),
            # الخليج العربي
            ("SAR", "Money", "ريال سعودي",            "amount",   "Saudi Arabia",        Decimal("0.27")),
            ("AED", "Money", "درهم إماراتي",          "amount",   "United Arab Emirates",Decimal("0.27")),
            ("KWD", "Money", "دينار كويتي",          "amount",   "Kuwait",              Decimal("3.25")),
            ("QAR", "Money", "ريال قطري",             "amount",   "Qatar",               Decimal("0.27")),
            ("OMR", "Money", "ريال عُماني",           "amount",   "Oman",                Decimal("2.60")),
            ("BHD", "Money", "دينار بحريني",          "amount",   "Bahrain",             Decimal("2.65")),
            # بلاد الشام والعراق
            ("SYP", "Money", "ليرة سورية",            "amount",   "Syria",               Decimal("0.00006")),
            ("LBP", "Money", "ليرة لبنانية",          "amount",   "Lebanon",             Decimal("0.000011")),
            ("IQD", "Money", "دينار عراقي",           "amount",   "Iraq",                Decimal("0.00076")),
            ("TRY", "Money", "ليرة تركية",            "amount",   "Turkey",              Decimal("0.030")),
            ("JOD", "Money", "دينار أردني",           "amount",   "Jordan",              Decimal("1.41")),
            # شرق آسيا
            ("MYR", "Money", "رينغيت ماليزي",         "amount",   "Malaysia",            Decimal("0.21")),
            ("IDR", "Money", "روبية إندونيسية",       "amount",   "Indonesia",           Decimal("0.000065")),
            ("SGD", "Money", "دولار سنغافوري",        "amount",   "Singapore",           Decimal("0.74")),
            ("HKD", "Money", "دولار هونغ كونغ",       "amount",   "Hong Kong",           Decimal("0.13")),
            ("PHP", "Money", "بيزو فلبيني",           "amount",   "Philippines",         Decimal("0.017")),
        ]

        all_assets = metals + currencies

        for code, name, a_type, unit, country, price in all_assets:
            obj, created = Asset.objects.update_or_create(
                asset_code=code,
                defaults={
                    "name": name,
                    "asset_type": a_type,
                    "unit_name": unit,
                    "nationality": country,
                    "unit_price_usd": price,
                    "is_active": True,
                },
            )
            status = "Created" if created else "Updated"
            self.stdout.write(f"{status}: {code} ({price} USD per {unit})")

        self.stdout.write(self.style.SUCCESS("✅ Asset table seeded successfully with codes."))
