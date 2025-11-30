# app/views.py
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from django.db import transaction
from .serializers import *
from .models import Asset
from .utils import *
from .services import *
from datetime import datetime, timedelta, time
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiTypes

from .conf import *

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

@extend_schema(exclude=True)
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



@extend_schema(exclude=True)
class ZakatReferenceView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return success_response(data=ZAKAT_REFERENCE_JSON, message=["reference generated"])




class PrivacyPolicyView(APIView):
    permission_classes = [AllowAny]
    serializer_class = None  # لا يوجد body

    @extend_schema(
        tags=["Legal"],
        summary="سياسة الخصوصية",
        description="يعيد هيكل سياسة الخصوصية الخاص بتطبيق الزكاة على شكل JSON منظم.",
        request=None,
        responses={
            200: OpenApiResponse(
                description="Privacy policy JSON",
                response=OpenApiTypes.OBJECT
            )
        },
    )
    def get(self, request):
        return success_response(
            data=PRIVACY_POLICY_JSON,
            message=["privacy policy"]
        )



class TermsOfUseView(APIView):
    permission_classes = [AllowAny]
    serializer_class = None  

    def get(self, request):
        return success_response(
            data=TERMS_OF_USE_JSON,
            message=["terms of use"]
        )



class AboutView(APIView):
    permission_classes = [AllowAny]
    serializer_class = None

    def get(self, request):
        return success_response(
            data=ABOUT_JSON,
            message=["about"]
        )


class ContactInfoView(APIView):
    permission_classes = [AllowAny]
    serializer_class = None

    def get(self, request):
        return success_response(
            data=CONTACT_INFO_JSON,
            message=["contact_info"]
        )

# https://open.er-api.com/v6/latest/USD

# https://metalpriceapi.com/dashboard
#https://api.metalpriceapi.com/v1/latest?api_key=d9aac6787678279fbb25f9098ab579cc&base=USD&currencies=XAU,XAG
# {"success":true,"base":"USD","timestamp":1762300799,"rates":{"USDXAG":47.9822996751,"USDXAU":3996.5901093187,"XAG":0.0208410186,"XAU":0.0002502133}}


from rest_framework.permissions import IsAdminUser

@extend_schema(exclude=True)
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


@extend_schema(exclude=True)
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





class ReportsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = ReportsInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user_id   = ser.validated_data["user_id"]
        filt_type = ser.validated_data.get("filter", "none")
        start_date = ser.validated_data.get("start_date")
        end_date   = ser.validated_data.get("end_date")

        # احسب حدود التاريخ (شاملة) بحسب الفلتر
        start_dt = end_dt = None
        tz = timezone.get_current_timezone()
        now = timezone.now()

        def day_start(d):  # 00:00:00
            return timezone.make_aware(datetime.combine(d, time.min), tz)

        def day_end(d):    # 23:59:59.999999
            return timezone.make_aware(datetime.combine(d, time.max), tz)

        if filt_type == "last_1m":
            start_dt = now - timedelta(days=30)
            start_dt = datetime.combine(start_dt.date(), time.min).replace(tzinfo=tz)
            end_dt   = datetime.combine(now.date(), time.max).replace(tzinfo=tz)

        elif filt_type == "last_3m":
            start_dt = now - timedelta(days=90)
            start_dt = datetime.combine(start_dt.date(), time.min).replace(tzinfo=tz)
            end_dt   = datetime.combine(now.date(), time.max).replace(tzinfo=tz)

        elif filt_type == "last_6m":
            start_dt = now - timedelta(days=180)
            start_dt = datetime.combine(start_dt.date(), time.min).replace(tzinfo=tz)
            end_dt   = datetime.combine(now.date(), time.max).replace(tzinfo=tz)

        elif filt_type == "custom":
            # start_date / end_date تأتي من الـ serializer بشكل Date
            start_dt = day_start(start_date)
            end_dt   = day_end(end_date)

        # none => بدون فلترة زمنية

        result = compute_user_report(request.user, user_id, start_dt=start_dt, end_dt=end_dt)
        if result.get("status") == "forbidden":
            return error_response(errors=["Not allowed."], status_code=403)
        if result.get("status") != "ok":
            return error_response(errors=result.get("message") or ["Failed to compute report."])

        return success_response(data=result, message=["Report computed."])





class TransferUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        """
        يعدّل مناقلة قائمة.
        body مثال:
        {
          "transfer_id": 123,
          "asset_id": 4,               // اختياري
          "type": "ADD",               // اختياري: ADD|WITHDRAW|ZAKAT_OUT
          "quantity": "12.5",          // اختياري (>=0)
          "note": "تعديل تجريبي",      // اختياري
          "bill_base64": "data:image/png;base64,....", // اختياري (يستبدل الموجودة)
          "bill_clear": false          // اختياري: true لحذف الصورة
        }
        """
        ser = TransferUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # جلب المناقلة
        try:
            transfer = Transfer.objects.select_for_update().get(id=data["transfer_id"])
        except Transfer.DoesNotExist:
            return error_response(errors=["Transfer not found"], status_code=404)

        # صلاحيات: المالك أو مشرف
        user = request.user
        if not (user.is_superuser or transfer.user_id == user.id):
            return error_response(errors=["Not allowed for this transfer"], status_code=403)

        # تعديل الحقول الآمنة فقط
        updated_fields = []

        if "asset_id" in data:
            asset = Asset.objects.get(id=data["asset_id"])
            if transfer.asset_id != asset.id:
                transfer.asset = asset
                updated_fields.append("asset")

        if "type" in data:
            t = data["type"].upper().strip()
            if transfer.transfer_type != t:
                transfer.transfer_type = t
                updated_fields.append("transfer_type")

        if "quantity" in data:
            q = data["quantity"]
            # الأموال quantity = مقدار (amount) وهو نفس الحقل هنا
            if transfer.quantity != q:
                transfer.quantity = q
                updated_fields.append("quantity")

        if "note" in data:
            n = data.get("note")
            if transfer.note != n:
                transfer.note = n
                updated_fields.append("note")

        # صورة الفاتورة
        if data.get("bill_clear", False):
            if getattr(transfer, "bill", None):
                transfer.bill.delete(save=False)
            transfer.bill = None
            updated_fields.append("bill")
        elif "bill_base64" in data:
            try:
                content = decode_base64_image(data["bill_base64"])
            except ValueError:
                return error_response(errors=["Invalid base64 image"], status_code=400)
            if getattr(transfer, "bill", None):
                transfer.bill.delete(save=False)
            transfer.bill = content
            updated_fields.append("bill")

        # إن لم يغيّر شيء
        if not updated_fields:
            return success_response(message=["No changes"], data={"transfer_id": transfer.id})

        transfer.save()  # بدون update_fields كي نضمن إشارات الحفظ

        return success_response(
            message=["Transfer updated successfully"],
            data={
                "transfer_id": transfer.id,
                "updated_fields": updated_fields,
            },
        )











