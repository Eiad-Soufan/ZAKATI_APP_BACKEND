from rest_framework.response import Response
from rest_framework import status

def success_response(data=None, message=None, code=200):
    return Response({
        "message": message or [],
        "data": data or {}
    }, status=status.HTTP_200_OK)

def error_response(errors=None, code=500):
    # نحول جميع الأخطاء إلى قائمة رسائل نصية فقط
    messages = []
    if isinstance(errors, dict):
        for field, msgs in errors.items():
            if isinstance(msgs, (list, tuple)):
                messages.extend(msgs)
            else:
                messages.append(str(msgs))
    elif isinstance(errors, (list, tuple)):
        messages.extend(errors)
    elif errors:
        messages.append(str(errors))

    return Response({
        "message": messages,
        "data": {}
    }, status=status.HTTP_400_BAD_REQUEST)



# utils.py (أضِف في الأسفل مثلًا)
import base64
import imghdr
import uuid
from django.core.files.base import ContentFile

def decode_base64_image(data_str: str):
    """
    يقبل:
      - data URL مثل: data:image/png;base64,AAAA...
      - أو Base64 خام: AAAA...
    يعيد ContentFile باسم فريد + امتداد صحيح.
    """
    if not data_str:
        return None

    # افصل الهيدر لو كان data URL
    if "base64," in data_str:
        header, data_str = data_str.split("base64,", 1)

    try:
        decoded = base64.b64decode(data_str)
    except Exception:
        raise ValueError("Invalid base64 image")

    # حاول تحديد الامتداد
    ext = imghdr.what(None, h=decoded) or "jpg"
    if ext == "jpeg":
        ext = "jpg"

    file_name = f"{uuid.uuid4().hex}.{ext}"
    return ContentFile(decoded, name=file_name)


