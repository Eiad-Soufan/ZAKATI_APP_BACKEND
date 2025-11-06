# app/views.py
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.db import transaction
from .serializers import *
from .models import Asset
from rest_framework.views import APIView
from .utils import *
from .services import *

# --------------------------
# تسجيل مستخدم جديد
# --------------------------
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response(serializer.errors)
        user = serializer.save()
        data = {"email": user.email}
        return success_response(data=data, message=["تم إنشاء الحساب بنجاح."])


# --------------------------
# تسجيل دخول
# --------------------------
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            tokens = serializer.validated_data
            return success_response(data=tokens, message=["تم تسجيل الدخول بنجاح."])
        except Exception as e:
            # استخراج تفاصيل الخطأ من الاستثناء
            detail = getattr(e, "detail", str(e))
            return error_response(detail)


# --------------------------
# تحديث الـ access token
# --------------------------
class RefreshTokenView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response(serializer.errors)
        return success_response(data=serializer.validated_data, message=["تم تحديث التوكن بنجاح."])


# --------------------------
# تعديل البروفايل
# --------------------------
class ProfileUpdateView(generics.UpdateAPIView):
    serializer_class = ProfileUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response(serializer.errors)
        serializer.save()
        return success_response(data=serializer.data, message=["تم تحديث الملف الشخصي."])


# --------------------------
# قائمة العملات
# --------------------------
class AssetListView(generics.ListAPIView):
    queryset = Asset.objects.filter( is_active=True)
    serializer_class = AssetSerializer
    permission_classes = [permissions.AllowAny]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)



# قبل:
# class SetDisplayCurrencyView(APIView):


class SetDisplayCurrencyView(generics.GenericAPIView):
    serializer_class = SetDisplayCurrencySerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return error_response(serializer.errors)
        user, asset = serializer.save()
        data = {
            "user_id": user.id,
            "display_currency": {
                "id": asset.id,
                "asset_code": asset.asset_code,
                "name": asset.name,
                "nationality": asset.nationality,
                "unit_price_usd": str(asset.unit_price_usd),
            }
        }
        return success_response(data=data, message=["تم تعيين عملة العرض بنجاح."])




# app/views.py
from rest_framework import generics, permissions
from .serializers import TransferCreateSerializer, TransferSerializer
from .utils import success_response, error_response

class TransferCreateView(generics.GenericAPIView):
    serializer_class = TransferCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return error_response(serializer.errors)
        transfer = serializer.save()
        data = TransferSerializer(transfer).data
        return success_response(data=data, message=["تم إنشاء المناقلة بنجاح."])





##############################################################
# GET /api/snapshot/?limit=20
# Authorization: Bearer <access_token>

# GET /api/snapshot/
# Authorization: Bearer <access_token>

# app/views.py (مقتطف SnapshotView)
from rest_framework import permissions, generics
from .utils import success_response
from .services import compute_user_snapshot, grouped_transfers
from .serializers import TransferSerializer

class SnapshotView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        snap = compute_user_snapshot(user)

        # limit اختياري
        limit_param = request.query_params.get("limit")
        limit = int(limit_param) if (limit_param and limit_param.isdigit() and int(limit_param) > 0) else None

        groups = grouped_transfers(user, limit=limit)
        transfers_payload = {
            "gold":   TransferSerializer(groups["gold"], many=True).data,
            "silver": TransferSerializer(groups["silver"], many=True).data,
            "money":  TransferSerializer(groups["money"], many=True).data,
        }

        profile = {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "phone_number": user.phone_number,
            "country": user.country,
            "city": user.city,
            "avatar_url": (user.avatar.url if user.avatar else None),
        }

        data = {
            "profile": profile,
            "display_currency": snap["display_currency"],
            "totals": snap["totals"],
            "classes": snap["classes"],
            "notifications": snap["notifications"],   # تذكيرات قبل الموعد فقط
            "transfers": transfers_payload,          # كل المناقلات بروابط الصور
        }
        return success_response(data=data, message=["snapshot generated"])


# app/views.py (مرجعية الزكاة بصيغة JSON)
from rest_framework import permissions, generics
from .utils import success_response

ZAKAT_REFERENCE_JSON = {
    "title": "مرجعية الزكاة (فقهًا وتطبيقًا)",
    "lang": "ar",
    "version": "1.0.0",
    "structure": {
        "sections": [
            {
                "id": "intro",
                "title": "مقدمة وتعريف",
                "body": "الزكاة ركن من أركان الإسلام الخمسة، وهي حق واجب في المال إذا بلغ النصاب وحال عليه الحول، وتُصرف لمستحقيها الثمانية المذكورين في القرآن. تختلف عن الصدقة النافلة إذ للزكاة شروط ومقادير محددة."
            },
            {
                "id": "dalil",
                "title": "الأدلة الشرعية المختصرة",
                "subsections": [
                    {
                        "title": "القرآن الكريم",
                        "verses": [
                            {"ref": "البقرة: 43، 110", "text": "وأقيموا الصلاة وآتوا الزكاة"},
                            {"ref": "التوبة: 103", "text": "خذ من أموالهم صدقة تطهرهم وتزكيهم بها"},
                            {"ref": "التوبة: 60", "text": "إنما الصدقات للفقراء ... (مصارف الزكاة الثمانية)"}
                        ]
                    },
                    {
                        "title": "السنة الصحيحة",
                        "hadiths": [
                            {"ref": "متفق عليه", "text": "بني الإسلام على خمس ... وإيتاء الزكاة"},
                            {"ref": "البخاري، مسلم", "text": "ليس فيما دون خمس أواقٍ صدقة (200 درهم ≈ 595غ فضة)"},
                            {"ref": "البخاري", "text": "وفي الرِّقَةِ ربع العشر (2.5%)"}
                        ],
                        "notes": "نصاب الذهب مقدّر بـ 20 مثقالًا ≈ 85 غرامًا خالصًا، وهو الجاري في المذاهب الأربعة."
                    }
                ]
            },
            {
                "id": "zakatable_supported",
                "title": "الأموال الزكوية التي يدعمها التطبيق",
                "bullets": [
                    "الذهب: جميع العيارات ويُقوَّم بالسعر الجاري للغرام.",
                    "الفضة.",
                    "النقود والعملات (USD, MYR, وغيرها)."
                ],
                "note": "السلع التجارية/الأسهم/الديون يمكن دعمها لاحقًا بنفس منطق الحول والنصاب."
            },
            {
                "id": "conditions",
                "title": "شروط الوجوب",
                "bullets": [
                    "الملك التام (مال مملوك غير معلَّق).",
                    "بلوغ النصاب: الذهب 85غ 24K، الفضة 595غ تقريبًا، النقود تُقاس على أحدهما (المعمول به غالبًا الذهب).",
                    "الحول القمري: مرور سنة هجرية (~354 يومًا) والمال فوق النصاب طوالها؛ إن نزل قبل الإتمام انقطع الحول."
                ]
            },
            {
                "id": "rate",
                "title": "مقدار الزكاة",
                "body": "ربع العشر (2.5%) من صافي المال الزكوي عند تمام الحول، للذهب/الفضة/النقود."
            },
            {
                "id": "how_app_calculates",
                "title": "منهج الحساب في التطبيق (بدقة فقهية)",
                "subsections": [
                    {
                        "title": "الحول والنصاب (لكل فئة على حدة)",
                        "bullets": [
                            "يبدأ الحول عند أول لحظة يبلغ فيها مجموع الفئة النصاب.",
                            "إذا هبطت القيمة تحت النصاب قبل إكمال الحول: يُلغى الحول ويُستأنف عند بلوغه مجددًا.",
                            "عند اكتمال الحول تُثبَت الزكاة الواجبة."
                        ]
                    },
                    {
                        "title": "قيمة الوعاء عند الاستحقاق",
                        "body": "يحتسب التطبيق قيمة الفئة بالدولار عند لحظة الاستحقاق (due_at) اعتمادًا على خط الزمن المستخلص من المناقلات، ثم يطبق 2.5%."
                    },
                    {
                        "title": "السداد بعد الحول",
                        "bullets": [
                            "يجمع التطبيق ما دُفع من زكاة (ZAKAT_OUT) منذ due_at.",
                            "إذا غطّى المدفوع كامل الواجب: تُقفل الدورة ويبدأ حول جديد من تاريخ الاستحقاق نفسه (لا من يوم الدفع).",
                            "إذا كان السداد جزئيًا: يُظهر المتبقّي حتى يُستوفى."
                        ]
                    },
                    {
                        "title": "الهبوط تحت النصاب بعد الاستحقاق",
                        "body": "لا يُسقط الواجب؛ يبقى المتبقّي في الذمة حتى يُدفع."
                    },
                    {
                        "title": "عملة العرض",
                        "body": "تُسعّر القيم بالدولار أولًا ثم تُحَوَّل إلى عملة العرض عبر القسمة على unit_price_usd للعملة المختارة من جدول الأصول."
                    }
                ]
            },
            {
                "id": "scenarios",
                "title": "سيناريوهات مغطّاة",
                "bullets": [
                    "بلغ النصاب اليوم ⇒ يبدأ الحول اليوم، ولا زكاة قبل مرور 354 يومًا.",
                    "هبط تحت النصاب قبل الإتمام ⇒ يُلغى الحول ويُستأنف لاحقًا عند بلوغه مجددًا.",
                    "اكتمل الحول والمال فوق النصاب ⇒ تظهر الزكاة الواجبة (2.5% من قيمة الفئة عند due_at).",
                    "تأخر السداد ⇒ يبقى المتبقّي واجبًا حتى يُدفع.",
                    "سُدِّدت كامل الزكاة بعد الاستحقاق ⇒ يبدأ حول جديد من تاريخ الاستحقاق نفسه.",
                    "سُدِّد جزء فقط ⇒ يظهر المتبقّي ولا تبدأ دورة جديدة حتى الاكتمال.",
                    "إن لم تُحدَّد عملة عرض: العرض بالدولار."
                ]
            },
            {
                "id": "references",
                "title": "مراجع موثوقة ",
                "references": [
                    {"type": "Quran", "name": "البقرة: 43، 110", "note": "إقامة الصلاة وإيتاء الزكاة"},
                    {"type": "Quran", "name": "التوبة: 60", "note": "مصارف الزكاة الثمانية"},
                    {"type": "Quran", "name": "التوبة: 103", "note": "أخذ الصدقة لتطهير المال"},
                    {"type": "Hadith", "name": "حديث الأركان", "source": "متفق عليه", "note": "وجوب الزكاة"},
                    {"type": "Hadith", "name": "خمس أواقٍ (200 درهم ≈ 595غ)", "source": "البخاري، مسلم"},
                    {"type": "Hadith", "name": "ربع العشر (2.5%)", "source": "البخاري"},
                    {"type": "Madhahib", "name": "المجموع شرح المهذب", "author": "النووي (شافعي)"},
                    {"type": "Madhahib", "name": "المغني", "author": "ابن قدامة (حنبلي)"},
                    {"type": "Madhahib", "name": "بدائع الصنائع", "author": "الكاساني (حنفي)"},
                    {"type": "Madhahib", "name": "رد المحتار", "author": "ابن عابدين (حنفي)"},
                    {"type": "Madhahib", "name": "المدونة/الذخيرة", "author": "القرافي وآخرون (مالكي)"},
                    {"type": "Comparative", "name": "بداية المجتهد ونهاية المقتصد", "author": "ابن رشد"},
                    {"type": "FiqhBodies", "name": "مجمع الفقه الإسلامي الدولي (OIC)", "note": "قرارات الزكاة"},
                    {"type": "FiqhBodies", "name": "هيئة كبار العلماء (السعودية)", "note": "فتاوى معتمدة"},
                    {"type": "Standards", "name": "AAOIFI – معيار الزكاة", "note": "المعايير الشرعية للمؤسسات المالية الإسلامية"},
                    {"type": "ZakatInstitutions", "name": "بيت الزكاة (الكويت) ولجان رسمية", "note": "أدلة إجرائية"}
                ],
                "disclaimer": "اقتصرنا على القرآن والسنة الصحيحة وما عليه المذاهب الأربعة وجهات معيارية معتبرة، وتجنّبنا المرويات الضعيفة والمراجع المختلف عليها."
            }
        ]
    }
}

class ZakatReferenceView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return success_response(data=ZAKAT_REFERENCE_JSON, message=["reference generated"])


# https://open.er-api.com/v6/latest/USD

# https://metalpriceapi.com/dashboard
#https://api.metalpriceapi.com/v1/latest?api_key=d9aac6787678279fbb25f9098ab579cc&base=USD&currencies=XAU,XAG
# {"success":true,"base":"USD","timestamp":1762300799,"rates":{"USDXAG":47.9822996751,"USDXAU":3996.5901093187,"XAG":0.0208410186,"XAU":0.0002502133}}


from rest_framework.permissions import IsAdminUser

# Temporary Available APIs, Schedule and delete from here and from services
class UpdateCurrencyRatesView(APIView):
    permission_classes = [permissions.AllowAny]  #IsAdminUser

    def post(self, request):
        """
        يستدعي خدمة تحديث أسعار صرف العملات من ER-API ويعيد تقريراً بالنتيجة.
        استدعِه بعمل POST فقط.
        """
        result = update_currency_assets_from_erapi()
        if result.get("status") == "ok":
            return success_response(data=result, message=["Currency assets updated from ER-API."])
        else:
            return error_response(errors=result.get("message") or ["Update failed"])


class UpdateMetalRatesView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """
        يحدّث أسعار الذهب (24/21/19) والفضة بالدولار/غرام من metalpriceapi.
        يتوقع إرسال api_key في البودي (JSON) أو في الإعدادات لاحقًا.
        """
        result = update_metals_assets_from_metalpriceapi(api_key='d9aac6787678279fbb25f9098ab579cc')
        if result.get("status") == "ok":
            return success_response(data=result, message=["Metal assets updated from metalpriceapi."])
        else:
            return error_response(errors=result.get("message") or ["Update failed"])
