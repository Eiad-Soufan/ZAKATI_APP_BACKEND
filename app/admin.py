from django.contrib import admin

# Register your models here.
from django.contrib import admin
from django.utils.html import format_html
from .models import Asset, User, Transfer


# ==========================
#  Asset Admin
# ==========================
@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "asset_code",
        "name",
        "asset_type",
        "unit_name",
        "unit_price_usd",
        "nationality",
        "is_active",
    )
    list_filter = ("asset_type", "unit_name", "is_active")
    search_fields = ("asset_code", "name", "asset_type", "nationality")
    ordering = ("asset_type", "asset_code")
    list_editable = ("is_active",)
    readonly_fields = ("id",)
    list_per_page = 25

    fieldsets = (
        (None, {
            "fields": (
                "asset_code",
                "name",
                "asset_type",
                "unit_name",
                "unit_price_usd",
                "nationality",
                "is_active",
            )
        }),
    )


# ==========================
#  User Admin
# ==========================
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "full_name",
        "country",
        "city",
        "phone_number",
        "display_currency_code",
        "avatar_preview",
        "is_active",
        "is_staff",
    )
    list_filter = ("is_active", "is_staff", "country")
    search_fields = ("email", "full_name", "country", "city", "phone_number")
    ordering = ("email",)
    list_per_page = 25

    fieldsets = (
        ("Personal Info", {
            "fields": (
                "email",
                "full_name",
                "phone_number",
                "country",
                "city",
                "avatar",
                "display_currency",
            )
        }),
        ("Permissions", {
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
        }),
        ("Authentication", {"fields": ("password",)}),
    )

    def display_currency_code(self, obj):
        """عرض رمز العملة بدلًا من الاسم الكامل"""
        return obj.display_currency.asset_code if obj.display_currency else "-"
    display_currency_code.short_description = "Currency"

    def avatar_preview(self, obj):
        """صورة مصغّرة أنيقة في قائمة المستخدمين"""
        if obj.avatar:
            return format_html('<img src="{}" width="40" height="40" style="border-radius:50%; object-fit:cover;" />', obj.avatar.url)
        return "-"
    avatar_preview.short_description = "Avatar"


# ==========================
#  Transfer Admin
# ==========================
@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_email",
        "asset_code",
        "transfer_type",
        "quantity",
        "transfer_date",
        "note_short",
    )
    list_filter = ("transfer_type", "asset__asset_type")
    search_fields = (
        "user__email",
        "user__full_name",
        "asset__asset_code",
        "asset__name",
        "note",
    )
    ordering = ("-transfer_date",)
    list_per_page = 25

    fieldsets = (
        (None, {
            "fields": (
                "user",
                "asset",
                "transfer_type",
                "quantity",
                "transfer_date",
                "note",
            )
        }),
    )

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = "User Email"

    def asset_code(self, obj):
        return obj.asset.asset_code
    asset_code.short_description = "Asset"

    def note_short(self, obj):
        """عرض ملاحظات مختصرة"""
        if not obj.note:
            return "-"
        return (obj.note[:40] + "...") if len(obj.note) > 40 else obj.note
    note_short.short_description = "Note"
