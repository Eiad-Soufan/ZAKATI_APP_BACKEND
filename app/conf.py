# app/conf.py
from datetime import timedelta

# نسبة الزكاة
ZAKAT_RATE = 0.025

# الحول بالايام (هجري ≈ 354)
ZAKAT_HAUL_DAYS = 354

# نصاب الذهب/الفضة
NISAB_GOLD_GRAMS = 85
NISAB_SILVER_GRAMS = 595

# معيار نصاب "الأموال" (اختَر GOLD أو SILVER؛ المعتمد غالباً GOLD)
NISAB_BENCHMARK_FOR_MONEY = "GOLD"

# تذكيرات قبل موعد الزكاة (أيام) — لا إشعار تأخير
ZAKAT_REMINDER_OFFSETS = [30, 15, 7, 0]
