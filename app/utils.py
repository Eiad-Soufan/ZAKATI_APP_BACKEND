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
