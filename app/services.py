# app/services.py

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, Any, List, Optional, Tuple

from django.utils import timezone
from django.db.models import Sum, F
from django.db.models.functions import Coalesce
from django.db import transaction

from .models import Asset, Transfer, User
from .conf import (
    ZAKAT_RATE, ZAKAT_HAUL_DAYS,
    NISAB_GOLD_GRAMS, NISAB_SILVER_GRAMS,
    NISAB_BENCHMARK_FOR_MONEY, ZAKAT_REMINDER_OFFSETS
)

from datetime import datetime, time
import requests




# Update Currencies and Metals
METAL_API_URL = "https://api.metalpriceapi.com/v1/latest"
OUNCE_TROY_TO_GRAM = Decimal("31.1034768")
ERAPI_URL = "https://open.er-api.com/v6/latest/USD"
TRANSFER_DATE_FIELD = "transfer_date"  

# -------- أدوات رقمية --------
DEC6 = lambda x: (x if isinstance(x, Decimal) else Decimal(str(x))).quantize(Decimal("0.000001"))
def now_utc(): return timezone.now()

# -------- عملة العرض --------
def get_display_currency(user: User) -> Optional[Asset]:
    if user.display_currency and user.display_currency.unit_name == "amount":
        return user.display_currency
    return Asset.objects.filter(asset_code="USD", is_active=True).first()

def usd_to_display(usd_value: Decimal, display_asset: Optional[Asset]) -> Decimal:
    if not display_asset or Decimal(display_asset.unit_price_usd) == 0:
        return DEC6(usd_value)
    return DEC6(Decimal(usd_value) / Decimal(display_asset.unit_price_usd))

# -------- تسعير --------
def metal_grams_to_usd(grams: Decimal, metal_asset: Asset) -> Decimal:
    return DEC6(Decimal(grams) * Decimal(metal_asset.unit_price_usd))

def money_amount_to_usd(amount: Decimal, money_asset: Asset) -> Decimal:
    return DEC6(Decimal(amount) * Decimal(money_asset.unit_price_usd))

# -------- مجاميع بسيطة --------
def sum_quantity(user: User, asset_ids: List[int], transfer_type: str) -> Decimal:
    return DEC6(
        Transfer.objects.filter(user=user, asset_id__in=asset_ids, transfer_type=transfer_type)
        .aggregate(s=Sum("quantity"))["s"] or Decimal("0")
    )

# -------- خط الزمن لقيمة الفئة بالدولار --------
def running_balance_usd_for_class(user: User, assets: List[Asset]) -> Tuple[Decimal, List[Tuple[datetime, Decimal]]]:
    """
    يعيد:
      running (USD): القيمة الحالية للفئة
      timeline: [(ts, value_usd_after_this_tx)] تصاعديًا
    """
    asset_ids = [a.id for a in assets]
    qs = (Transfer.objects.filter(user=user, asset_id__in=asset_ids)
          .order_by("transfer_date", "id")
          .select_related("asset"))

    running = Decimal("0")
    timeline: List[Tuple[datetime, Decimal]] = []
    for t in qs:
        if t.asset.unit_name == "gram":
            delta = metal_grams_to_usd(t.quantity, t.asset)
        else:
            delta = money_amount_to_usd(t.quantity, t.asset)

        if t.transfer_type == "ADD":
            running += delta
        elif t.transfer_type in ("WITHDRAW", "ZAKAT_OUT"):
            running -= delta

        running = DEC6(running)
        timeline.append((t.transfer_date, running))

    return running, timeline

def value_at_datetime_from_timeline(timeline: List[Tuple[datetime, Decimal]], dt: datetime) -> Decimal:
    """
    قيمة الفئة بالدولار عند لحظة dt: نأخذ آخر قيمة <= dt إن وُجدت،
    وإن كانت كل الأحداث بعد dt نعيد 0.
    """
    last = Decimal("0")
    for ts, val in timeline:
        if ts <= dt:
            last = val
        else:
            break
    return DEC6(last)

# -------- النصاب بالدولار --------
def nisab_usd_for_gold() -> Decimal:
    a = Asset.objects.filter(asset_code="GOLD_24", is_active=True).first()
    if a: return DEC6(Decimal(NISAB_GOLD_GRAMS) * Decimal(a.unit_price_usd))
    return DEC6(Decimal(NISAB_GOLD_GRAMS) * Decimal("75.0"))  # fallback

def nisab_usd_for_silver() -> Decimal:
    a = Asset.objects.filter(name="Silver", unit_name="gram", is_active=True).first()
    if a: return DEC6(Decimal(NISAB_SILVER_GRAMS) * Decimal(a.unit_price_usd))
    return DEC6(Decimal(NISAB_SILVER_GRAMS) * Decimal("1.0"))  # fallback

def nisab_usd_for_money() -> Decimal:
    return nisab_usd_for_silver() if NISAB_BENCHMARK_FOR_MONEY.upper()=="SILVER" else nisab_usd_for_gold()

# -------- تحديد نافذة الحول (بلغ النصاب واستمر) --------
def haul_window_from_timeline(timeline: List[Tuple[datetime, Decimal]], nisab_usd: Decimal) -> Dict[str, Any]:
    """
    نمشي على الخط الزمني:
      - متى تجاوزنا النصاب؟ start = أول نقطة value >= nisab
      - إذا هبط بعدها تحت النصاب قبل الإكمال → reset
      - في النهاية:
          * إن لا يوجد start → لم يبدأ الحول
          * إن يوجد start → قارن الفرق مع الآن
    """
    start: Optional[datetime] = None
    for ts, val in timeline:
        if val >= nisab_usd:
            if start is None:
                start = ts
        else:
            start = None

    now = now_utc()
    if start is None:
        return {
            "above_now": False,
            "haul_started_at": None,
            "completed_hawl": False,
            "next_due_date": None,
            "days_left": None,
        }

    days_passed = (now - start).days
    completed = days_passed >= ZAKAT_HAUL_DAYS
    next_due = start + timezone.timedelta(days=ZAKAT_HAUL_DAYS)
    days_left = (next_due - now).days if not completed else 0

    return {
        "above_now": True,
        "haul_started_at": start,
        "completed_hawl": completed,
        "next_due_date": next_due,
        "days_left": days_left,
    }

# -------- مجموع ما دُفع منذ الاستحقاق --------
def total_zakat_out_since(user: User, assets: List[Asset], since_dt: datetime) -> Decimal:
    qs = (Transfer.objects
          .filter(user=user, asset__in=assets, transfer_type="ZAKAT_OUT", transfer_date__gte=since_dt)
          .select_related("asset"))
    total = Decimal("0")
    for t in qs:
        if t.asset.unit_name == "gram":
            total += metal_grams_to_usd(t.quantity, t.asset)
        else:
            total += money_amount_to_usd(t.quantity, t.asset)
    return DEC6(total)

# -------- دورات الحول المكتملة (عدة سنوات) --------
def compute_overdue_zakat_cycles(
    timeline: List[Tuple[datetime, Decimal]],
    start: datetime,
    nisab_usd: Decimal,
) -> List[Dict[str, Any]]:
    """
    تحسب جميع الحوالات المكتملة (السنوات) ضمن شريحة زمنية متصلة
    تبدأ من start وحتى الآن، بشرط أن يبقى الرصيد عند كل تاريخ استحقاق
    فوق النصاب.
    """
    now = now_utc()
    days_since_start = (now - start).days
    if days_since_start < ZAKAT_HAUL_DAYS:
        return []

    max_cycles = days_since_start // ZAKAT_HAUL_DAYS
    cycles: List[Dict[str, Any]] = []
    for i in range(1, max_cycles + 1):
        due_at = start + timezone.timedelta(days=ZAKAT_HAUL_DAYS * i)
        if due_at > now:
            break

        # قيمة الرصيد عند تاريخ الاستحقاق
        val_at_due = value_at_datetime_from_timeline(timeline, due_at)

        # احتياط إضافي: لو كان أقل من النصاب عند هذا التاريخ نوقف (تجديد حول)
        if val_at_due < nisab_usd:
            break

        required = DEC6(val_at_due * Decimal(str(ZAKAT_RATE)))
        cycles.append({
            "due_at": due_at,
            "required_usd": required,
        })

    return cycles


def allocate_paid_over_cycles(
    total_paid_usd: Decimal,
    cycles: List[Dict[str, Any]],
) -> Tuple[Decimal, Optional[datetime]]:
    """
    توزّع مجموع الزكاة المدفوعة (دولار) على الحوالات بالترتيب (FIFO).
    ترجع:
      (total_remaining_usd, earliest_unpaid_due_at)
    حيث:
      - total_remaining_usd: مجموع الزكاة المتبقية عن كل السنوات
      - earliest_unpaid_due_at: تاريخ أقدم حول غير مسدَّد (إن وجد)
    """
    remaining_paid = DEC6(total_paid_usd)
    total_remaining = Decimal("0")
    earliest_unpaid: Optional[datetime] = None

    for c in cycles:
        required = c["required_usd"]
        remaining_for_cycle = required

        if remaining_paid > 0:
            used = required if remaining_paid >= required else remaining_paid
            remaining_for_cycle = DEC6(required - used)
            remaining_paid = DEC6(remaining_paid - used)

        c["remaining_usd"] = remaining_for_cycle

        if remaining_for_cycle > 0 and earliest_unpaid is None:
            earliest_unpaid = c["due_at"]

        total_remaining = DEC6(total_remaining + remaining_for_cycle)

    return total_remaining, earliest_unpaid

    
# -------- حساب فئة واحدة (ذهب/فضة/أموال) --------
def compute_class_snapshot(user: User, kind: str) -> Dict[str, Any]:
    display = get_display_currency(user)

    if kind == "gold":
        assets = list(Asset.objects.filter(name="Gold", unit_name="gram", is_active=True))
        nisab_usd = nisab_usd_for_gold()
    elif kind == "silver":
        assets = list(Asset.objects.filter(name="Silver", unit_name="gram", is_active=True))
        nisab_usd = nisab_usd_for_silver()
    elif kind == "money":
        assets = list(Asset.objects.filter(name="Money", unit_name="amount", is_active=True))
        nisab_usd = nisab_usd_for_money()
    else:
        raise ValueError("Unknown kind")

    # عناصر الفئة (صافي كمية كل أصل + قيمته)
    items: List[Dict[str, Any]] = []
    total_usd = Decimal("0")
    for a in assets:
        add = sum_quantity(user, [a.id], "ADD")
        sub = sum_quantity(user, [a.id], "WITHDRAW")
        zak = sum_quantity(user, [a.id], "ZAKAT_OUT")
        net = DEC6(add - sub - zak)
        if net == 0:
            continue

        if a.unit_name == "gram":
            val_usd = metal_grams_to_usd(net, a)
            items.append({
                "asset_id": a.id, "asset_code": a.asset_code, "unit": "gram",
                "quantity": str(net), "value_usd": str(val_usd),
                "value_display": str(usd_to_display(val_usd, display)),
            })
        else:
            val_usd = money_amount_to_usd(net, a)
            items.append({
                "asset_id": a.id, "asset_code": a.asset_code, "unit": "amount",
                "quantity": str(net), "value_usd": str(val_usd),
                "value_display": str(usd_to_display(val_usd, display)),
            })
        total_usd += val_usd

    total_usd = DEC6(total_usd)

    # خط الزمن للفئة (بالدولار) + نافذة الحول
    running_usd, timeline = running_balance_usd_for_class(user, assets)
    haul = haul_window_from_timeline(timeline, nisab_usd)

    # الواجب الزكوي (قد يكون عن سنة واحدة أو عدة سنوات مكتملة)
    zakat_due_usd = Decimal("0")

    if haul["above_now"] and haul["completed_hawl"]:
        start = haul["haul_started_at"]

        # في الوضع الطبيعي start لن يكون None هنا، لكن نتحوّط
        if start is not None:
            #  1) احسب جميع الحوالات المكتملة من بداية هذه الشريحة
            cycles = compute_overdue_zakat_cycles(timeline, start, nisab_usd)
        else:
            cycles = []

        if cycles:
            first_due = cycles[0]["due_at"]

            # إجمالي الواجب عن جميع الحوالات المكتملة (سنة، سنتين، ثلاث...)
            total_required = DEC6(sum(c["required_usd"] for c in cycles))

            # مجموع ما دُفع من الزكاة منذ أول موعد استحقاق
            # (أي دفعات زائدة تُعتبر مقدّمة للسنوات التالية)
            total_paid = total_zakat_out_since(user, assets, first_due)

            # وزّع المدفوع على الحوالات بالترتيب (FIFO: الأقدم فالأقدم)
            total_remaining, earliest_unpaid_due = allocate_paid_over_cycles(total_paid, cycles)

            if total_remaining > 0:
                # يوجد زكاة متأخرة عن سنة أو أكثر — لا يضيع شيء من حيث القيمة
                zakat_due_usd = total_remaining

                # نحافظ على شكل حقل haul كما هو، لكن نربطه بأقدم حول غير مسدَّد
                now = now_utc()
                next_due = earliest_unpaid_due or first_due
                days_left = (next_due - now).days  # غالبًا 0 أو سالب إن كان متأخرًا

                haul = {
                    "above_now": True,
                    "haul_started_at": start,
                    "completed_hawl": True,
                    "next_due_date": next_due,
                    "days_left": days_left,
                }
            else:
                #  لا يوجد أي متبقٍ عن الحوالات الماضية:
                #    - إن كان دفع أكثر من اللازم → تُعتبر زكاة مقدّمة
                #    - يبدأ حول جديد من آخر تاريخ استحقاق
                zakat_due_usd = Decimal("0")

                last_due = cycles[-1]["due_at"]
                new_start = last_due
                now = now_utc()
                next_due = new_start + timezone.timedelta(days=ZAKAT_HAUL_DAYS)
                days_left = (next_due - now).days

                haul = {
                    "above_now": running_usd >= nisab_usd,
                    "haul_started_at": new_start,
                    "completed_hawl": False,
                    "next_due_date": next_due,
                    "days_left": days_left,
                }
        else:
            #  fallback: لو لأي سبب لم تُستخرج دورات متعددة، نعود للمنطق السابق (حول واحد)
            due_at = haul["next_due_date"]  # تاريخ الاستحقاق

            base_usd_at_due = value_at_datetime_from_timeline(timeline, due_at)
            required = DEC6(base_usd_at_due * Decimal(str(ZAKAT_RATE)))

            paid = total_zakat_out_since(user, assets, due_at)
            remaining = required - paid

            if remaining <= 0:
                #  دُفعت زكاة هذه الدورة (ولو بعد الموعد) — يعاد ضبط الحول كما كان سابقاً
                new_start = due_at
                now = now_utc()
                cycles_count = max(0, ((now - new_start).days // ZAKAT_HAUL_DAYS))
                current_cycle_start = new_start + timezone.timedelta(days=cycles_count * ZAKAT_HAUL_DAYS)
                next_due = current_cycle_start + timezone.timedelta(days=ZAKAT_HAUL_DAYS)
                days_left = (next_due - now).days

                haul = {
                    "above_now": running_usd >= nisab_usd,
                    "haul_started_at": current_cycle_start,
                    "completed_hawl": False,
                    "next_due_date": next_due,
                    "days_left": days_left,
                }
                zakat_due_usd = Decimal("0")
            else:
                # لم يُسدَّد كامل الواجب — أبقِ الاستحقاق الماضي وأظهر المتبقي
                zakat_due_usd = DEC6(remaining)
                # days_left سيبقى 0 أو سالباً (إن مرّ الموعد) بحسب haul_window
    else:
        # لم يكتمل الحول أو لا يزال تحت النصاب — لا زكاة واجبة الآن
        zakat_due_usd = Decimal("0")

    return {
        "items": items,
        "total_value_usd": str(total_usd),
        "total_value_display": str(usd_to_display(total_usd, display)),
        "nisab_usd": str(nisab_usd),
        "haul": {
            "above_now": haul["above_now"],
            "haul_started_at": haul["haul_started_at"],
            "completed_hawl": haul["completed_hawl"],
            "next_due_date": haul["next_due_date"],
            "days_left": haul["days_left"],
        },
        "zakat": {
            "rate": ZAKAT_RATE,
            "zakat_due_usd": str(zakat_due_usd),
            "zakat_due_display": str(usd_to_display(zakat_due_usd, display)),
        }
    }


# -------- إشعارات قبل الموعد فقط --------
def build_notifications_for_class(class_snapshot: Dict[str, Any]) -> List[str]:
    msgs = []
    haul = class_snapshot["haul"]
    if not haul["above_now"]:
        return msgs
    days_left = haul["days_left"]
    if days_left is None:
        return msgs
    for d in ZAKAT_REMINDER_OFFSETS:
        if days_left == d:
            msgs.append("حان موعد الزكاة اليوم." if d == 0 else f"تبقّى {d} يومًا على موعد الزكاة.")
    return msgs


def compute_combined_gold_money_zakat(user: User) -> Decimal:
    """
    تحسب الزكاة الواجبة (بالدولار) على مجموع الأثمان:
      - Gold (gram)
      - Silver (gram)
      - Money (amount)
    بنفس منطق الحول المتعدد والزكاة المتأخرة.
    النتيجة: إجمالي الزكاة المستحقة الآن على الكل.
    """

    # جميع أصول الأثمان
    gold_assets = list(Asset.objects.filter(name="Gold", unit_name="gram", is_active=True))
    silver_assets = list(Asset.objects.filter(name="Silver", unit_name="gram", is_active=True))
    money_assets = list(Asset.objects.filter(name="Money", unit_name="amount", is_active=True))

    assets = gold_assets + silver_assets + money_assets
    if not assets:
        return Decimal("0")

    # خط الزمن لقيمة المجموع (ذهب + فضة + أموال)
    running_usd, timeline = running_balance_usd_for_class(user, assets)

    # نصاب المال بناء على الإعداد NISAB_BENCHMARK_FOR_MONEY (ذهب/فضة)
    nisab_usd = nisab_usd_for_money()

    haul = haul_window_from_timeline(timeline, nisab_usd)
    zakat_due_usd = Decimal("0")

    # فقط لو المال الآن فوق النصاب ومر عليه حول قمري كامل
    if haul["above_now"] and haul["completed_hawl"]:
        start = haul["haul_started_at"]

        if start is not None:
            cycles = compute_overdue_zakat_cycles(timeline, start, nisab_usd)
        else:
            cycles = []

        if cycles:
            # أول تاريخ استحقاق
            first_due = cycles[0]["due_at"]

            # مجموع ما دفعه المستخدم كزكاة (ZAKAT_OUT) منذ أول استحقاق
            total_paid = total_zakat_out_since(user, assets, first_due)

            # وزّع المدفوع على السنوات بالترتيب (FIFO)
            total_remaining, earliest_unpaid_due = allocate_paid_over_cycles(total_paid, cycles)

            if total_remaining > 0:
                zakat_due_usd = DEC6(total_remaining)

    return zakat_due_usd


def compute_user_snapshot(user: User) -> Dict[str, Any]:
    display = get_display_currency(user)

    # اللقطات المنفصلة لكل فئة (كما هي – لا نغيّر منطقها الداخلي)
    gold = compute_class_snapshot(user, "gold")
    silver = compute_class_snapshot(user, "silver")
    money = compute_class_snapshot(user, "money")

    # إجمالي القيمة بالدولار
    total_usd = DEC6(
        Decimal(gold["total_value_usd"]) +
        Decimal(silver["total_value_usd"]) +
        Decimal(money["total_value_usd"])
    )

    # --- جديد: زكاة مجموع الأثمان (ذهب + فضة + أموال) ---
    combined_zakat_usd = compute_combined_gold_money_zakat(user)
    combined_zakat_usd = DEC6(combined_zakat_usd)
    combined_zakat_display = usd_to_display(combined_zakat_usd, display)

    # نضع الزكاة النهائية في "money" فقط كما تريد
    # ونصفّر الزكاة الظاهرة في الذهب والفضة (عرض فقط، لا يمس الحول أو الحساب الداخلي)
    zero_usd = Decimal("0")
    zero_display = usd_to_display(zero_usd, display)

    gold["zakat"]["zakat_due_usd"] = "0"
    gold["zakat"]["zakat_due_display"] = str(zero_display)

    silver["zakat"]["zakat_due_usd"] = "0"
    silver["zakat"]["zakat_due_display"] = str(zero_display)

    money["zakat"]["zakat_due_usd"] = str(combined_zakat_usd)
    money["zakat"]["zakat_due_display"] = str(combined_zakat_display)

    # الإشعارات تبقى تبع كل فئة كما هي (اعتمادًا على haul لكل واحدة)
    notifications: List[str] = []
    notifications += build_notifications_for_class(gold)
    notifications += build_notifications_for_class(silver)
    notifications += build_notifications_for_class(money)

    return {
        "display_currency": {
            "asset_id": (display.id if display else None),
            "asset_code": (display.asset_code if display else "USD"),
            "unit_price_usd": str(display.unit_price_usd) if display else "1.000000",
        },
        "totals": {
            "total_value_usd": str(total_usd),
            "total_value_display": str(usd_to_display(total_usd, display)),
        },
        "classes": {
            "gold": gold,
            "silver": silver,
            "money": money,
        },
        "notifications": notifications,
    }


# حساب الزكاة لكل اصل مختلف عن الاخر
# def compute_user_snapshot(user: User) -> Dict[str, Any]:
#     display = get_display_currency(user)

#     gold = compute_class_snapshot(user, "gold")
#     silver = compute_class_snapshot(user, "silver")
#     money = compute_class_snapshot(user, "money")

#     total_usd = DEC6(Decimal(gold["total_value_usd"]) + Decimal(silver["total_value_usd"]) + Decimal(money["total_value_usd"]))

#     notifications: List[str] = []
#     notifications += build_notifications_for_class(gold)
#     notifications += build_notifications_for_class(silver)
#     notifications += build_notifications_for_class(money)

#     return {
#         "display_currency": {
#             "asset_id": (display.id if display else None),
#             "asset_code": (display.asset_code if display else "USD"),
#             "unit_price_usd": str(display.unit_price_usd) if display else "1.000000",
#         },
#         "totals": {
#             "total_value_usd": str(total_usd),
#             "total_value_display": str(usd_to_display(total_usd, display)),
#         },
#         "classes": {
#             "gold": gold,
#             "silver": silver,
#             "money": money,
#         },
#         "notifications": notifications,
#     }

# -------- تجميع المناقلات للرد --------
def grouped_transfers(user: User, limit: Optional[int] = None) -> Dict[str, List[Transfer]]:
    gold_ids = list(Asset.objects.filter(name="Gold", unit_name="gram", is_active=True).values_list("id", flat=True))
    silver_ids = list(Asset.objects.filter(name="Silver", unit_name="gram", is_active=True).values_list("id", flat=True))
    money_ids = list(Asset.objects.filter(name="Money", unit_name="amount", is_active=True).values_list("id", flat=True))

    def fetch(ids):
        qs = (Transfer.objects
              .filter(user=user, asset_id__in=ids)
              .order_by("-transfer_date", "-id"))
        return list(qs[:limit]) if limit else list(qs)

    return {
        "gold": fetch(gold_ids),
        "silver": fetch(silver_ids),
        "money": fetch(money_ids),
    }


######################################################
######################################################
######################################################
# Update Currencies and Metals
def update_currency_assets_from_erapi() -> dict:
    from .models import Asset

    updated, skipped, missing_code, errors = [], [], [], []

    try:
        resp = requests.get(ERAPI_URL, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        return {"status": "error", "message": [f"HTTP/JSON error: {e}"],
                "updated": updated, "skipped": skipped,
                "missing_code": missing_code, "errors": errors}

    if payload.get("result") != "success" or "rates" not in payload:
        return {"status": "error", "message": ["Unexpected payload from ER-API."],
                "updated": updated, "skipped": skipped,
                "missing_code": missing_code, "errors": errors}

    rates = payload["rates"]

    # نحدّد الدقة من تعريف الحقل نفسه
    dec_places = getattr(Asset._meta.get_field("unit_price_usd"), "decimal_places", 6)
    q = Decimal("1").scaleb(-dec_places)  # مثال: 6 -> Decimal('0.000001')

    qs = Asset.objects.filter(name="Money", unit_name="amount", is_active=True)

    @transaction.atomic
    def _do_update():
        for a in qs.select_for_update():
            code = (a.asset_code or "").upper().strip()
            if not code:
                missing_code.append(a.id)
                continue
            if code not in rates:
                skipped.append({"asset_id": a.id, "code": code, "reason": "code_not_in_response"})
                continue

            try:
                per_usd = Decimal(str(rates[code]))  # كم عملة أجنبية مقابل 1 USD
                if per_usd <= 0:
                    skipped.append({"asset_id": a.id, "code": code, "reason": "non_positive_rate"})
                    continue

                usd_per_unit = (Decimal("1") / per_usd).quantize(q, rounding=ROUND_HALF_UP)

                if a.unit_price_usd != usd_per_unit:
                    old = a.unit_price_usd
                    a.unit_price_usd = usd_per_unit
                    # ملاحظة: أزلنا updated_at لأنه غير موجود في الموديل
                    a.save(update_fields=["unit_price_usd"])
                    updated.append({"asset_id": a.id, "code": code, "old": str(old), "new": str(usd_per_unit)})
                else:
                    skipped.append({"asset_id": a.id, "code": code, "reason": "no_change"})
            except (InvalidOperation, Exception) as e:
                errors.append({"asset_id": a.id, "code": code, "error": str(e)})

    _do_update()

    return {
        "status": "ok",
        "message": [f"Processed {qs.count()} money assets"],
        "updated": updated, "skipped": skipped,
        "missing_code": missing_code, "errors": errors,
        "time_last_update_utc": payload.get("time_last_update_utc"),
        "time_next_update_utc": payload.get("time_next_update_utc"),
        "base_code": payload.get("base_code"),
    }


def _quantize_to_field(value: Decimal, model_cls, field_name: str) -> Decimal:
    dec_places = getattr(model_cls._meta.get_field(field_name), "decimal_places", 6)
    q = Decimal("1").scaleb(-dec_places)  # مثال: 6 -> 0.000001
    return value.quantize(q, rounding=ROUND_HALF_UP)

def update_metals_assets_from_metalpriceapi(api_key: str) -> dict:
    """
    يجلب سعر الذهب/الفضة من metalpriceapi (USD base) ويحدّث:
      GOLD_24, GOLD_21, GOLD_19  (بالغرام)
      SILVER (بالغرام)
    """
    from .models import Asset

    updated, skipped, missing, errors = [], [], [], []

    # --- 1) جلب البيانات من API ---
    try:
        resp = requests.get(
            METAL_API_URL,
            params={"api_key": api_key, "base": "USD", "currencies": "XAU,XAG"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        return {"status": "error", "message": [f"HTTP/JSON error: {e}"],
                "updated": updated, "skipped": skipped,
                "missing": missing, "errors": errors}

    if not payload.get("success"):
        return {"status": "error", "message": ["Unexpected payload from metalpriceapi."],
                "updated": updated, "skipped": skipped,
                "missing": missing, "errors": errors}

    rates = payload.get("rates") or {}
    # نحاول أخذ USD/oz مباشرة؛ وإلا نستخدم 1 / XAU (oz/USD) كاحتياط
    try:
        usd_per_oz_gold  = Decimal(str(rates.get("USDXAU"))) if rates.get("USDXAU") else (Decimal("1") / Decimal(str(rates["XAU"])))
        usd_per_oz_silver = Decimal(str(rates.get("USDXAG"))) if rates.get("USDXAG") else (Decimal("1") / Decimal(str(rates["XAG"])))
        if usd_per_oz_gold <= 0 or usd_per_oz_silver <= 0:
            raise InvalidOperation("Non-positive metal rate")
    except Exception as e:
        return {"status": "error", "message": [f"Bad metal rates: {e}"],
                "updated": updated, "skipped": skipped,
                "missing": missing, "errors": errors}

    # --- 2) تحويل إلى دولار/غرام ---
    gold24_usd_per_g = usd_per_oz_gold  / OUNCE_TROY_TO_GRAM
    silver_usd_per_g = usd_per_oz_silver / OUNCE_TROY_TO_GRAM

    # عيارات الذهب الأخرى
    gold21_usd_per_g = gold24_usd_per_g * (Decimal(21) / Decimal(24))
    gold19_usd_per_g = gold24_usd_per_g * (Decimal(19) / Decimal(24))

    # --- 3) تحديث السجلات المستهدفة ---
    targets = {
        "GOLD_24": gold24_usd_per_g,
        "GOLD_21": gold21_usd_per_g,
        "GOLD_19": gold19_usd_per_g,
        "SILVER":  silver_usd_per_g,
    }

    qs = Asset.objects.filter(asset_code__in=list(targets.keys()), is_active=True)

    @transaction.atomic
    def _do_update():
        for a in qs.select_for_update():
            try:
                new_val = _quantize_to_field(targets[a.asset_code], Asset, "unit_price_usd")
                if a.unit_name != "gram":
                    # لتجنّب أي ارتباك لو كانت الوحدة مختلفة
                    skipped.append({"asset_id": a.id, "code": a.asset_code, "reason": f"unexpected_unit:{a.unit_name}"})
                    continue
                if a.unit_price_usd != new_val:
                    old = a.unit_price_usd
                    a.unit_price_usd = new_val
                    a.save(update_fields=["unit_price_usd"])
                    updated.append({"asset_id": a.id, "code": a.asset_code, "old": str(old), "new": str(new_val)})
                else:
                    skipped.append({"asset_id": a.id, "code": a.asset_code, "reason": "no_change"})
            except KeyError:
                missing.append({"asset_id": a.id, "code": a.asset_code})
            except Exception as e:
                errors.append({"asset_id": a.id, "code": a.asset_code, "error": str(e)})

    _do_update()

    return {
        "status": "ok",
        "message": [f"Processed {qs.count()} metal assets"],
        "updated": updated, "skipped": skipped,
        "missing": missing, "errors": errors,
        "timestamp": payload.get("timestamp"),
        "base": payload.get("base"),
    }


def _q(val: Decimal, places=6) -> Decimal:
    q = Decimal("1").scaleb(-places)  # 6 -> 0.000001
    return (val or Decimal("0")).quantize(q, rounding=ROUND_HALF_UP)

def compute_user_report(user, target_user_id: int, start_dt=None, end_dt=None) -> dict:
    """
    يحسب تقرير التحويلات (Transfers) لمستخدم معيّن.
    - الأصول المُضافة: نوع ADD
    - الأصول المسحوبة: نوع WITHDRAW
    - الزكاة المدفوعة: نوع ZAKAT_OUT
    * الذهب/الفضة: كمية بالغرام وقيمتها USD و بعملة العرض
    * الأموال: لا تُعاد الكمية، فقط القيم USD و بعملة العرض
    * عملة العرض: display_currency على المستخدم؛ وإن لم توجد → USD
    """
    from .models import Transfer, Asset, User

    # صلاحية الوصول: المالك نفسه أو مشرف
    if (not user.is_superuser) and (user.id != target_user_id):
        return {"status": "forbidden", "message": ["Not allowed for this user_id."]}

    # جلب عملة العرض
    try:
        target_user = User.objects.get(id=target_user_id)
    except User.DoesNotExist:
        return {"status": "error", "message": ["User not found."]}

    display_asset = getattr(target_user, "display_currency", None)  # قد تكون FK إلى Asset
    if not display_asset:
        # افتراض USD
        display_asset = Asset.objects.filter(asset_code="USD", is_active=True).first()

    # عامل التحويل: كم (وحدة عرض) لكل 1 USD
    # note: unit_price_usd = USD per 1 unit => display_per_usd = 1 / unit_price_usd
    if display_asset and display_asset.unit_price_usd and display_asset.unit_price_usd > 0:
        display_per_usd = Decimal("1") / display_asset.unit_price_usd
        display_code = display_asset.asset_code
    else:
        display_per_usd = Decimal("1")
        display_code = "USD"

    def usd_to_display(amount_usd: Decimal) -> Decimal:
        return _q((amount_usd or Decimal("0")) * display_per_usd)

    # جميع تحويلات المستخدم
    qs = Transfer.objects.select_related("asset").filter(user_id=target_user_id)
    if start_dt and end_dt:
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())
        date_filters = {
            f"{TRANSFER_DATE_FIELD}__gte": start_dt,
            f"{TRANSFER_DATE_FIELD}__lte": end_dt,
        }
        qs = qs.filter(**date_filters)
    # ثوابت الأنواع (كما هي في الجدول)
    TYPE_ADD = "ADD"
    TYPE_WITHDRAW = "WITHDRAW"
    TYPE_ZAKAT = "ZAKAT_OUT"

    # سنجمع بقيم USD: (الكمية × سعر الأصل بالدولار)
    # ملاحظة: الأموال (Money) لها unit_name="amount" ولا نعرض quantity لها.

    def base_bucket():
        return {
            "gold":   {"quantity_gram": Decimal("0"), "value_usd": Decimal("0"), "value_display": Decimal("0")},
            "silver": {"quantity_gram": Decimal("0"), "value_usd": Decimal("0"), "value_display": Decimal("0")},
            "money":  {"value_usd": Decimal("0"), "value_display": Decimal("0")},  # لا كمية للأموال
        }

    added     = base_bucket()
    withdrawn = base_bucket()
    zakat_out = base_bucket()

    # نكرّر على التحويلات ونصنّف حسب Asset.name (Gold/Silver/Money)
    for t in qs:
        a = t.asset
        if not a or not a.is_active:
            continue

        cls = (a.name or "").strip().lower()  # "gold"/"silver"/"money"
        qty = t.quantity or Decimal("0")
        # قيمة USD: الكمية × سعر الأصل بالدولار (لكل غرام للمعادن، لكل وحدة عملة للأموال)
        value_usd = (qty * (a.unit_price_usd or Decimal("0")))

        if cls == "gold":
            if t.transfer_type  == TYPE_ADD:
                added["gold"]["quantity_gram"] += qty
                added["gold"]["value_usd"] += value_usd
            elif t.transfer_type  == TYPE_WITHDRAW:
                withdrawn["gold"]["quantity_gram"] += qty
                withdrawn["gold"]["value_usd"] += value_usd
            elif t.transfer_type  == TYPE_ZAKAT:
                zakat_out["gold"]["quantity_gram"] += qty
                zakat_out["gold"]["value_usd"] += value_usd

        elif cls == "silver":
            if t.transfer_type  == TYPE_ADD:
                added["silver"]["quantity_gram"] += qty
                added["silver"]["value_usd"] += value_usd
            elif t.transfer_type  == TYPE_WITHDRAW:
                withdrawn["silver"]["quantity_gram"] += qty
                withdrawn["silver"]["value_usd"] += value_usd
            elif t.transfer_type  == TYPE_ZAKAT:
                zakat_out["silver"]["quantity_gram"] += qty
                zakat_out["silver"]["value_usd"] += value_usd

        elif cls == "money":
            if t.transfer_type  == TYPE_ADD:
                added["money"]["value_usd"] += value_usd
            elif t.transfer_type  == TYPE_WITHDRAW:
                withdrawn["money"]["value_usd"] += value_usd
            elif t.transfer_type  == TYPE_ZAKAT:
                zakat_out["money"]["value_usd"] += value_usd

    # تحويل USD إلى عملة العرض وتجهيز التقريب
    for bucket in (added, withdrawn, zakat_out):
        # gold
        bucket["gold"]["quantity_gram"] = _q(bucket["gold"]["quantity_gram"])
        bucket["gold"]["value_usd"] = _q(bucket["gold"]["value_usd"])
        bucket["gold"]["value_display"] = usd_to_display(bucket["gold"]["value_usd"])
        # silver
        bucket["silver"]["quantity_gram"] = _q(bucket["silver"]["quantity_gram"])
        bucket["silver"]["value_usd"] = _q(bucket["silver"]["value_usd"])
        bucket["silver"]["value_display"] = usd_to_display(bucket["silver"]["value_usd"])
        # money (no quantity)
        bucket["money"]["value_usd"] = _q(bucket["money"]["value_usd"])
        bucket["money"]["value_display"] = usd_to_display(bucket["money"]["value_usd"])

    # سطر سعر الصرف: "1 USD = X CODE"
    fx_line = f"1 USD = {_q(display_per_usd)} {display_code}"

    return {
        "status": "ok",
        "display_currency": display_code,
        "fx_line": fx_line,
        "filter": {
            "enabled": bool(start_dt and end_dt),
            "start": start_dt.isoformat() if start_dt else None,
            "end":   end_dt.isoformat() if end_dt else None,
        },
        "added": added,
        "withdrawn": withdrawn,
        "zakat_out": zakat_out,
    }







