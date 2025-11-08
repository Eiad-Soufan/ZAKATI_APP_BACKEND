# app/services.py

from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

from django.utils import timezone
from django.db.models import Sum

from .models import Asset, Transfer, User
from .conf import (
    ZAKAT_RATE, ZAKAT_HAUL_DAYS,
    NISAB_GOLD_GRAMS, NISAB_SILVER_GRAMS,
    NISAB_BENCHMARK_FOR_MONEY, ZAKAT_REMINDER_OFFSETS
)
# services.py (أعلى الملف أو قرب دالة التقرير)
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP


TRANSFER_DATE_FIELD = "created_at"  # ← عدّلها إن كان الحقل اسمه 'occurred_at' مثلاً

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
    items = []
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

    # الواجب الزكوي لهذه الدورة (إن اكتمل الحول)
    zakat_due_usd = Decimal("0")

    if haul["above_now"] and haul["completed_hawl"]:
        due_at = haul["next_due_date"]  # تاريخ الاستحقاق

        # ⚠️ الواجب يُحسب على قيمة الفئة عند due_at (من خطّ الزمن)
        base_usd_at_due = value_at_datetime_from_timeline(timeline, due_at)
        required = DEC6(base_usd_at_due * Decimal(str(ZAKAT_RATE)))

        # احسب المدفوع منذ due_at
        paid = total_zakat_out_since(user, assets, due_at)
        remaining = required - paid

        if remaining <= 0:
            # ✅ دُفعت زكاة الدورة المكتملة (ولو بعد الموعد):
            # تبدأ دورة جديدة من due_at نفسه، ولا ننقل البداية إلى يوم الدفع.
            new_start = due_at
            now = now_utc()
            # إن مر وقت طويل، حدّد بداية الدورة الجارية الحالية بحيث تبقى المواعيد سنوية ثابتة
            cycles = max(0, ((now - new_start).days // ZAKAT_HAUL_DAYS))
            current_cycle_start = new_start + timezone.timedelta(days=cycles * ZAKAT_HAUL_DAYS)
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
        # لم يكتمل الحول أو لا يزال تحت النصاب
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

# -------- تجميعة المستخدم --------
def compute_user_snapshot(user: User) -> Dict[str, Any]:
    display = get_display_currency(user)

    gold = compute_class_snapshot(user, "gold")
    silver = compute_class_snapshot(user, "silver")
    money = compute_class_snapshot(user, "money")

    total_usd = DEC6(Decimal(gold["total_value_usd"]) + Decimal(silver["total_value_usd"]) + Decimal(money["total_value_usd"]))

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
import requests
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db import transaction
METAL_API_URL = "https://api.metalpriceapi.com/v1/latest"
OUNCE_TROY_TO_GRAM = Decimal("31.1034768")
ERAPI_URL = "https://open.er-api.com/v6/latest/USD"

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




# services.py (أضِف في الأسفل مثلاً)
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, F
from django.db.models.functions import Coalesce

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
            if t.type == TYPE_ADD:
                added["gold"]["quantity_gram"] += qty
                added["gold"]["value_usd"] += value_usd
            elif t.type == TYPE_WITHDRAW:
                withdrawn["gold"]["quantity_gram"] += qty
                withdrawn["gold"]["value_usd"] += value_usd
            elif t.type == TYPE_ZAKAT:
                zakat_out["gold"]["quantity_gram"] += qty
                zakat_out["gold"]["value_usd"] += value_usd

        elif cls == "silver":
            if t.type == TYPE_ADD:
                added["silver"]["quantity_gram"] += qty
                added["silver"]["value_usd"] += value_usd
            elif t.type == TYPE_WITHDRAW:
                withdrawn["silver"]["quantity_gram"] += qty
                withdrawn["silver"]["value_usd"] += value_usd
            elif t.type == TYPE_ZAKAT:
                zakat_out["silver"]["quantity_gram"] += qty
                zakat_out["silver"]["value_usd"] += value_usd

        elif cls == "money":
            if t.type == TYPE_ADD:
                added["money"]["value_usd"] += value_usd
            elif t.type == TYPE_WITHDRAW:
                withdrawn["money"]["value_usd"] += value_usd
            elif t.type == TYPE_ZAKAT:
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

