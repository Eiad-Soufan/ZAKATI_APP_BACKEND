"""
Django settings for zakati2 project.
Django 5.x
"""

from pathlib import Path
from datetime import timedelta
import os
import dj_database_url

# =========================
# مسارات وأساسيات
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")  # غيّرها في الإنتاج
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
AUTH_USER_MODEL = "app.User"

# =========================
# تطبيقات
# =========================
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # طرف ثالث
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",

    # JWT Blacklist مطلوبة لأنك فعلت BLACKLIST_AFTER_ROTATION
    "rest_framework_simplejwt.token_blacklist",

    # وسائط سحابية
    "cloudinary",
    "cloudinary_storage",

    # محلي
    "app",
]

# =========================
# Middlewares
# =========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # يجب أن تكون قبل CommonMiddleware
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "zakati2.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],  # اتركه فارغًا إن لم تستخدم القوالب
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "zakati2.wsgi.application"

# =========================
# قاعدة البيانات
# =========================
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",  # افتراضي محلي/تجريبي
        conn_max_age=600,  # اتصالات مستدامة
        ssl_require=os.getenv("RENDER", "") == "true",   # فعّل SSL على Render
    )
}

if os.getenv("DATABASE_URL"):
    DATABASES["default"] = dj_database_url.parse(
        os.environ["DATABASE_URL"], conn_max_age=600, ssl_require=True
    )

# =========================
# كلمات المرور
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# اللغة والوقت
# =========================
LANGUAGE_CODE = "ar"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Kuala_Lumpur")
USE_I18N = True
USE_TZ = True

# =========================
# ملفات ستاتيك وميديا
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

MEDIA_URL = "/media/"
MEDIA_ROOT = os.getenv("MEDIA_ROOT", os.path.join(BASE_DIR, "media"))

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "LOCATION": MEDIA_ROOT,
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# STORAGES = {
#     "default": {
#         "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
#     },
#     "staticfiles": {
#         "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
#     },
# }

# CLOUDINARY_STORAGE = {
#     "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME"),
#     "API_KEY": os.getenv("CLOUDINARY_API_KEY"),
#     "API_SECRET": os.getenv("CLOUDINARY_API_SECRET"),
# }


# إعدادات Cloudinary من البيئة
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    "API_KEY": os.getenv("CLOUDINARY_API_KEY", ""),
    "API_SECRET": os.getenv("CLOUDINARY_API_SECRET", ""),
}
# في حال لم تضبط Cloudinary، سيستخدم MEDIA_ROOT محليًا عبر django-storages الافتراضي

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =========================
# DRF + JWT + Swagger
# =========================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "EXCEPTION_HANDLER": "app.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=90),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,  # يتطلب app: token_blacklist
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Zakati2 API",
    "DESCRIPTION": "Minimal Zakat API (snapshot-only, no user price control).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# =========================
# CORS / CSRF (للتطوير والواجهات)
# =========================
# أثناء التطوير
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "true").lower() == "true"
CORS_ALLOW_CREDENTIALS = True

# في الإنتاج، عطّل السطر أعلاه واستعمل القائمة أدناه:
CORS_ALLOWED_ORIGINS = [
    # "https://your-frontend.example.com",
]

CSRF_TRUSTED_ORIGINS = [
    # "https://your-frontend.example.com",
]

# =========================
# إعدادات أمان (فعّلها في الإنتاج)
# =========================
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_PRELOAD = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")



METALPRICE_API_KEY ='d9aac6787678279fbb25f9098ab579cc'