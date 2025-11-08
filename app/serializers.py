# app/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
import base64
from django.core.files.base import ContentFile
from .models import Asset

User = get_user_model()
# --------------------------
# تسجيل مستخدم جديد
# --------------------------
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ["email", "password"]

    def create(self, validated_data):
        email = validated_data["email"]
        password = validated_data["password"]

        # خذ الجزء قبل @ كـ username مبدئي
        base_username = email.split("@")[0][:150] or "user"

        # ضَمن فريد (لو موجود مسبقًا أضف لاحقة رقمية)
        username = base_username
        i = 1
        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        while UserModel.objects.filter(username=username).exists():
            suffix = f"-{i}"
            username = (base_username[:150 - len(suffix)] + suffix)
            i += 1

        user = UserModel.objects.create_user(
            username=username,
            email=email,
            password=password,
        )
        return user


# --------------------------
# تسجيل دخول JWT
# --------------------------
# app/serializers.py
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    # أكّد أننا نستخدم البريد كمُعرّف
    username_field = "email"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # استبدل حقل "username" بحقل "email"
        self.fields["email"] = serializers.EmailField()
        self.fields.pop("username", None)

    def validate(self, attrs):
        # اجلب البريد من email أو من username لو الفرونت أرسله بالغلط
        incoming_email = attrs.get("email") or self.initial_data.get("email") or self.initial_data.get("username")
        password = attrs.get("password") or self.initial_data.get("password")

        if not incoming_email:
            raise AuthenticationFailed("حقل البريد الإلكتروني مطلوب.")
        if not password:
            raise AuthenticationFailed("حقل كلمة المرور مطلوب.")

        # حدّث attrs بالحقل الصحيح الذي يتوقعه السوبر
        attrs[self.username_field] = incoming_email
        return super().validate(attrs)





class ProfileUpdateSerializer(serializers.ModelSerializer):
    avatar_base64 = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "full_name",
            "phone_number",
            "country",
            "city",
            "avatar_base64",
        ]

    def update(self, instance, validated_data):
        # معالجة الصورة المرسلة base64 إن وُجدت
        avatar_data = validated_data.pop("avatar_base64", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if avatar_data:
            try:
                # إزالة prefix مثل data:image/png;base64,
                format, imgstr = avatar_data.split(";base64,")
                ext = format.split("/")[-1]
                instance.avatar.save(
                    f"avatar_{instance.id}.{ext}",
                    ContentFile(base64.b64decode(imgstr)),
                    save=False
                )
            except Exception as e:
                raise serializers.ValidationError({"avatar_base64": f"Invalid image data: {e}"})

        instance.save()
        return instance



class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = [
            "id",
            "asset_code",
            "name",
            "asset_type",
            "unit_name",
            "nationality",
            "unit_price_usd",
        ]





# app/serializers.py
from rest_framework import serializers
from .models import Asset
from django.contrib.auth import get_user_model

User = get_user_model()

class SetDisplayCurrencySerializer(serializers.Serializer):  # ← انتبه Serializer وليس ModelSerializer
    asset_id = serializers.IntegerField(required=True)

    def validate_asset_id(self, value):
        qs = Asset.objects.filter(id=value, is_active=True, unit_name="amount")
        if not qs.exists():
            raise serializers.ValidationError("العملة غير موجودة أو غير صالحة للاستخدام.")
        return value

    def save(self, **kwargs):
        user: User = self.context["request"].user
        asset = Asset.objects.get(id=self.validated_data["asset_id"])
        user.display_currency = asset
        user.save(update_fields=["display_currency"])
        return user, asset




# app/serializers.py
from rest_framework import serializers
from django.utils import timezone
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from decimal import Decimal
import base64

from .models import Asset, Transfer

User = get_user_model()

TRANSFER_TYPE_CHOICES = [
    ("ADD", "ADD"),
    ("WITHDRAW", "WITHDRAW"),
    ("ZAKAT_OUT", "ZAKAT_OUT"),
]


class TransferSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    asset_code = serializers.CharField(source="asset.asset_code", read_only=True)
    bill_url = serializers.SerializerMethodField()

    class Meta:
        model = Transfer
        fields = [
            "id", "user", "user_email",
            "asset", "asset_code",
            "transfer_type", "quantity", "transfer_date",
            "note", "created_at",
            "bill_url",
        ]
        read_only_fields = ["id", "created_at", "bill_url"]

    def get_bill_url(self, obj):
        try:
            return obj.bill.url if obj.bill else None
        except Exception:
            return None


class TransferCreateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=True)
    asset_id = serializers.IntegerField(required=True)
    transfer_type = serializers.ChoiceField(choices=TRANSFER_TYPE_CHOICES)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=6)
    transfer_date = serializers.DateTimeField(required=False)  # اختياري
    note = serializers.CharField(required=False, allow_blank=True, max_length=240)
    bill_base64 = serializers.CharField(required=False, allow_blank=True)  # اختياري

    def validate_user_id(self, value):
        request = self.context["request"]
        if not request.user.is_staff and request.user.id != value:
            raise serializers.ValidationError("لا يمكنك إنشاء مناقلة لمستخدم آخر.")
        if not User.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("المستخدم غير موجود أو غير فعّال.")
        return value

    def validate_asset_id(self, value):
        if not Asset.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("الأصل غير موجود أو غير فعّال.")
        return value

    def validate_quantity(self, value: Decimal):
        if value <= 0:
            raise serializers.ValidationError("الكمية يجب أن تكون أكبر من الصفر.")
        return value

    def _decode_bill(self, bill_base64: str):
        """
        يفك ترميز data URL مثل: data:image/jpeg;base64,xxxx
        ويعيد (ext, ContentFile) أو None إذا المدخل فارغ.
        """
        if not bill_base64:
            return None
        try:
            if ";base64," in bill_base64:
                header, b64data = bill_base64.split(";base64,", 1)
                ext = header.split("/")[-1].lower()  # jpg/png/webp...
            else:
                # بدون هيدر
                b64data = bill_base64
                ext = "jpg"
            return ext, ContentFile(base64.b64decode(b64data))
        except Exception:
            raise serializers.ValidationError("صورة الفاتورة غير صالحة.")

    def create(self, validated_data):
        transfer_date = validated_data.get("transfer_date") or timezone.now()
        note = validated_data.get("note", "")
        bill_base64 = validated_data.get("bill_base64", "")

        user = User.objects.get(id=validated_data["user_id"])
        asset = Asset.objects.get(id=validated_data["asset_id"])

        # أنشئ السجل أولاً بدون الصورة
        transfer = Transfer.objects.create(
            user=user,
            asset=asset,
            transfer_type=validated_data["transfer_type"],
            quantity=validated_data["quantity"],
            transfer_date=transfer_date,
            note=note,
        )

        # احفظ الصورة إن وُجدت
        if bill_base64:
            decoded = self._decode_bill(bill_base64)
            if decoded:
                ext, content = decoded
                filename = f"bill_{transfer.id}.{ext}"
                transfer.bill.save(filename, content, save=True)

        return transfer



class ReportsInputSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)

# serializers.py
from rest_framework import serializers
from decimal import Decimal
from django.contrib.auth import get_user_model
from .models import Transfer, Asset

User = get_user_model()

TRANSFER_TYPES = {"ADD", "WITHDRAW", "ZAKAT_OUT"}

class TransferUpdateSerializer(serializers.Serializer):
    transfer_id = serializers.IntegerField(min_value=1)

    # الحقول القابلة للتعديل (كلها اختيارية)
    asset_id   = serializers.IntegerField(min_value=1, required=False)
    type       = serializers.CharField(required=False)
    quantity   = serializers.DecimalField(required=False, max_digits=18, decimal_places=6)
    note       = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # صورة الفاتورة Base64 أو أمر حذفها
    bill_base64 = serializers.CharField(required=False, allow_blank=False)
    bill_clear  = serializers.BooleanField(required=False, default=False)

    def validate_type(self, value):
        v = (value or "").upper().strip()
        if v not in TRANSFER_TYPES:
            raise serializers.ValidationError("Invalid transfer type. Allowed: ADD, WITHDRAW, ZAKAT_OUT")
        return v

    def validate_quantity(self, value: Decimal):
        if value is not None and value < 0:
            raise serializers.ValidationError("Quantity must be >= 0")
        return value

    def validate_asset_id(self, value):
        if not Asset.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Asset not found or inactive")
        return value



