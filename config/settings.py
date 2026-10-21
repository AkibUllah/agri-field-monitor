"""Django settings. Everything environment-specific comes from env vars (see .env.example)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def database_from_url(url: str) -> dict:
    """Parse ``sqlite:///path`` or ``postgres://user:pass@host:port/name``."""
    parsed = urlparse(url)
    if parsed.scheme.startswith("sqlite"):
        path = parsed.path or "/db.sqlite3"
        name = ":memory:" if path in ("/:memory:", ":memory:") else str(BASE_DIR / path.lstrip("/"))
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": name}
    if parsed.scheme in ("postgres", "postgresql"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": 60,
        }
    raise ValueError(f"unsupported DATABASE_URL scheme: {parsed.scheme}")


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)


def with_render_hostname(
    hosts: list[str], origins: list[str], hostname: str | None
) -> tuple[list[str], list[str]]:
    """Render publishes the public hostname as RENDER_EXTERNAL_HOSTNAME; allow it automatically."""
    hosts, origins = list(hosts), list(origins)
    if hostname:
        if hostname not in hosts:
            hosts.append(hostname)
        if f"https://{hostname}" not in origins:
            origins.append(f"https://{hostname}")
    return hosts, origins


ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS = with_render_hostname(
    env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1"),
    env_list("DJANGO_CSRF_TRUSTED_ORIGINS", ""),
    env("RENDER_EXTERNAL_HOSTNAME"),
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "strawberry_django",
    "apps.core",
    "apps.farms",
    "apps.monitoring",
    "apps.alerts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.JWTAuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": database_from_url(env("DATABASE_URL", "sqlite:///db.sqlite3"))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.core.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

# Domain settings
JWT_ALGORITHM = "HS256"
JWT_LIFETIME_HOURS = int(env("JWT_LIFETIME_HOURS", "12"))
AWD_THRESHOLD_CM = int(env("AWD_THRESHOLD_CM", "-15"))  # safe AWD: irrigate at 15 cm below surface
AWD_DAYS_BELOW_THRESHOLD = int(env("AWD_DAYS_BELOW_THRESHOLD", "2"))
SENSOR_SILENT_DAYS = int(env("SENSOR_SILENT_DAYS", "3"))
OVERFLOW_LEVEL_CM = int(env("OVERFLOW_LEVEL_CM", "10"))
PHOTO_MAX_BYTES = int(env("PHOTO_MAX_BYTES", str(5 * 1024 * 1024)))
PHOTO_ALLOWED_EXTENSIONS = env_list("PHOTO_ALLOWED_EXTENSIONS", "jpg,jpeg,png,webp")
GRAPHIQL = env_bool("GRAPHIQL", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.request": {"level": "WARNING"}},
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
