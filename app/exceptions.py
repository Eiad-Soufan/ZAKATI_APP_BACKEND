# app/exceptions.py
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import (
    ValidationError, NotAuthenticated, AuthenticationFailed,
    PermissionDenied, NotFound
)
from django.http import Http404
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied

def custom_exception_handler(exc, context):
    """
    توحيد شكل الاستجابة لكل الأخطاء:
    { "resultcode": 500, "message": [..], "data": {} }
    مع إبقاء status code المناسب (401/403/404/400/500)
    """
    # استجابة DRF الافتراضية (قد تكون None لبعض الأخطاء)
    response = exception_handler(exc, context)

    # تحديد كود HTTP المناسب
    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        http_status = status.HTTP_401_UNAUTHORIZED
        messages = [str(getattr(exc, "detail", "لم يتم تزويد بيانات الدخول."))]
    elif isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        http_status = status.HTTP_403_FORBIDDEN
        messages = ["ليست لديك صلاحية لتنفيذ هذا الطلب."]
    elif isinstance(exc, (NotFound, Http404)):
        http_status = status.HTTP_404_NOT_FOUND
        messages = ["العنصر غير موجود."]
    elif isinstance(exc, ValidationError):
        http_status = status.HTTP_400_BAD_REQUEST
        # تحويل تفاصيل الـ ValidationError إلى قائمة رسائل
        detail = getattr(exc, "detail", exc)
        messages = []
        if isinstance(detail, dict):
            for v in detail.values():
                if isinstance(v, (list, tuple)):
                    messages.extend([str(x) for x in v])
                else:
                    messages.append(str(v))
        elif isinstance(detail, (list, tuple)):
            messages.extend([str(x) for x in detail])
        else:
            messages.append(str(detail))
    else:
        # باقي الأخطاء
        http_status = response.status_code if response else status.HTTP_500_INTERNAL_SERVER_ERROR
        msg = getattr(exc, "detail", "حدث خطأ غير متوقع.")
        messages = [str(msg)]

    # جسم موحّد
    body = {
        "message": messages,
        "data": {}
    }
    return Response(body, status=http_status)
