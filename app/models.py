# app/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _

# دقة القيم المالية/الكميات
DECIMAL_18_6 = {"max_digits": 18, "decimal_places": 6}

class Asset(models.Model):
    # --------------------------
    # الخيارات الأساسية
    # --------------------------
    ASSET_NAME_CHOICES = [
        ("Gold", "ذهب"),
        ("Silver", "فضة"),
        ("Money", "اموال"),
    ]

    UNIT_NAME_CHOICES = [
        ("gram", "gram"),
        ("amount", "amount"),
    ]

    # --------------------------
    # الحقول
    # --------------------------
    name = models.CharField(_("Asset Name"), max_length=50, choices=ASSET_NAME_CHOICES)
    asset_type = models.CharField(_("Asset Type"), max_length=50)
    unit_name = models.CharField(_("Unit Name"), max_length=10, choices=UNIT_NAME_CHOICES)
    nationality = models.CharField(_("Nationality / Country"), max_length=80, blank=True, default="")
    asset_code = models.CharField(
        _("Asset Code"),
        max_length=10,
        unique=True,
        help_text=_("Short code such as USD, MYR, GOLD_24, SILVER, etc."),
    )
    unit_price_usd = models.DecimalField(
        _("Unit Price (USD)"),
        validators=[MinValueValidator(0)],
        **DECIMAL_18_6
    )
    is_active = models.BooleanField(default=True)

    # --------------------------
    # إعدادات الميتا
    # --------------------------
    class Meta:
        verbose_name = _("Asset")
        verbose_name_plural = _("Assets")
        indexes = [
            models.Index(fields=["asset_code"]),
            models.Index(fields=["asset_type"]),
            models.Index(fields=["name"]),
        ]
        ordering = ["asset_type", "asset_code"]

    def __str__(self):
        return f"{self.asset_code} - {self.name} ({self.asset_type})"


class User(AbstractUser):
    # أعدنا username كما هو (ليكون موجودًا في الداتابيس)
    username = models.CharField(max_length=150, unique=True)

    email = models.EmailField(_("email address"), unique=True)
    full_name = models.CharField(_("Full Name"), max_length=150)
    phone_number = models.CharField(_("Phone Number"), max_length=50, blank=True, default="")
    country = models.CharField(_("Country"), max_length=80, blank=True, default="")
    city = models.CharField(_("City"), max_length=80, blank=True, default="")
    avatar = models.ImageField(_("Avatar"), upload_to="avatars/", blank=True, null=True)

    display_currency = models.ForeignKey(
        Asset, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="users_using_as_display_currency",
        help_text=_("Must point to an Asset with unit_name='amount'."),
    )

    # نُبقي تسجيل الدخول بالبريد
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "full_name"]  # سيُطلب عند createsuperuser

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")

    def __str__(self):
        return self.full_name or self.email


    def clean(self):
        super().clean()
        if self.display_currency and self.display_currency.unit_name != "amount":
            from django.core.exceptions import ValidationError
            raise ValidationError({"display_currency": _("Display currency must be an Asset with unit_name='amount'.")})


class Transfer(models.Model):
    TRANSFER_TYPE_CHOICES = [
        ("ADD", "إضافة أصل"),
        ("WITHDRAW", "سحب أصل"),
        ("ZAKAT_OUT", "إخراج زكاة"),
    ]

    user = models.ForeignKey("app.User", on_delete=models.CASCADE, related_name="transfers")
    asset = models.ForeignKey("app.Asset", on_delete=models.PROTECT, related_name="transfers")
    transfer_type = models.CharField(
        max_length=12,
        choices=TRANSFER_TYPE_CHOICES,
        verbose_name=_("Transfer Type"),
    )

    quantity = models.DecimalField(validators=[MinValueValidator(0)], **DECIMAL_18_6)
    transfer_date = models.DateTimeField(verbose_name=_("Transfer Date"))
    note = models.CharField(max_length=240, blank=True, default="", verbose_name=_("Note"))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    bill = models.ImageField(_("Bill"), upload_to="bills/", blank=True, null=True)
    class Meta:
        verbose_name = _("Transfer")
        verbose_name_plural = _("Transfers")
        ordering = ["-transfer_date", "-id"]
        indexes = [
            models.Index(fields=["user", "transfer_date"]),
            models.Index(fields=["asset", "transfer_type"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.asset} - {self.get_transfer_type_display()} - {self.quantity}"
