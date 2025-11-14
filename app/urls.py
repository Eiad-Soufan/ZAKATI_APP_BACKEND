from django.urls import path
from .views import *

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", RefreshTokenView.as_view(), name="token_refresh"),
    path("profile/update/", ProfileUpdateView.as_view(), name="profile_update"),
    path("assets/", AssetListView.as_view(), name="assets_list"),
    path("profile/display-currency/", SetDisplayCurrencyView.as_view(), name="set_display_currency"),  # 👈 الجديد
    path("transfers/create/", TransferCreateView.as_view(), name="transfer_create"),
    path("snapshot/", SnapshotView.as_view(), name="snapshot"),
    path("reference/zakat/", ZakatReferenceView.as_view(), name="zakat_reference"),
    path("reference/privacy/", PrivacyPolicyView.as_view(), name="privacy-policy"),
    path("rates/update/currencies/", UpdateCurrencyRatesView.as_view(), name="update_currency_rates"),
    path("rates/update/metals/", UpdateMetalRatesView.as_view(), name="update_metal_rates"),
    path("reports/summary/", ReportsView.as_view(), name="reports_summary"),
    path("transfers/update/", TransferUpdateView.as_view(), name="transfer_update"),
]



