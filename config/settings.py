"""Django settings for Mentor.

Everything that differs between a laptop and the shop's server is read from the
environment, so this file is the same in both places and nothing secret lives
in git. Values come from a `.env` file beside manage.py -- see `.env.example`
for the full list, and DEPLOYMENT.md for what to put in it.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Real environment variables win over the file, so a service manager or an
# Apache SetEnv can override it without editing anything on disk.
load_dotenv(BASE_DIR / ".env", override=False)


def env_flag(name, default=False):
    """Read a boolean. "1", "true", "yes" and "on" all mean True."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name):
    """Read a comma-separated list, ignoring blanks and stray whitespace."""
    return [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]


# DEBUG defaults to False: forgetting to set it should fail safe, loudly and in
# development, rather than quietly leaking tracebacks on the shop's server.
DEBUG = env_flag("DEBUG", default=False)

# No fallback in production. An app running on a default key silently has
# forgeable sessions and password-reset tokens, so it must refuse to start.
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with:\n"
            "  python -c \"from django.core.management.utils import get_random_secret_key as k; print(k())\"\n"
            "and put it in the .env file beside manage.py."
        )
    SECRET_KEY = "django-insecure-development-key-not-for-deployment"

# Which hostnames the app will answer to, e.g. "mentor.local,192.168.1.50".
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS") or (["localhost", "127.0.0.1"] if DEBUG else [])

# Django 4+ needs the scheme here, e.g. "http://192.168.1.50,https://mentor.local".
# Without it, every POST from a non-localhost address is rejected as a CSRF failure.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'orders',
]

AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves everything in STATIC_ROOT itself, so the app does not depend on a
    # web server being configured to do it. On shared hosting -- cPanel and
    # friends -- there is often no way to add an Apache alias at all. Must sit
    # directly after SecurityMiddleware and before everything else.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'orders.context_processors.navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
#
# SQLite by default, which is a real choice rather than a placeholder: one shop,
# a handful of users, and reads vastly outnumbering writes. Set DB_ENGINE=mysql
# to point at XAMPP's MariaDB instead -- the models and queries are unchanged
# either way.

if os.environ.get("DB_ENGINE", "sqlite").lower() in {"mysql", "mariadb"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DB_NAME", "mentor"),
            "USER": os.environ.get("DB_USER", "root"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "OPTIONS": {
                # utf8mb4 so Greek product names and emoji survive the round
                # trip; STRICT_TRANS_TABLES so MySQL rejects bad data instead
                # of silently truncating it, which is SQLite's behaviour here.
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("DB_NAME") or BASE_DIR / "db.sqlite3",
        }
    }


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

# Stored timestamps stay UTC; only the display changes. Set TIME_ZONE in .env
# to the shop's own zone (Europe/Athens) so history reads in local time.
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'

# Shared CSS and JS live at the project root rather than inside one app,
# since base.html serves every page.
STATICFILES_DIRS = [BASE_DIR / 'static']

# Where `manage.py collectstatic` gathers everything for the web server to
# serve. With DEBUG off Django serves no static files at all, so skipping
# collectstatic gives a working app with no styling whatsoever.
STATIC_ROOT = BASE_DIR / 'staticfiles'


# Auth

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'order_list'
LOGOUT_REDIRECT_URL = 'login'

# Employees stay logged in across browser restarts (spec: persistent login).
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True  # sliding expiry: active users are not logged out


# Security
#
# Everything here is off unless HTTPS=1, and that is deliberate: switching a
# cookie to secure-only over plain HTTP does not warn, it just stops anyone
# logging in. Turn it on in the same change that puts a certificate on Apache.

HTTPS = env_flag("HTTPS", default=False)

SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SECURE_SSL_REDIRECT = HTTPS
# Start HSTS at an hour. Raising it later is easy; a browser that has cached a
# year of "HTTPS only" for a hostname cannot be told otherwise.
SECURE_HSTS_SECONDS = 3600 if HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS

# Behind Apache, Django only knows the request was HTTPS because Apache says so.
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"


# Logging
#
# With DEBUG off, an unhandled exception renders a bare 500 page and, by
# default, goes nowhere. These write it to logs/mentor.log so there is
# something to read when the shop says "it broke".

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "mentor.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "verbose",
        },
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["file", "console"], "level": "INFO"},
    "loggers": {
        # Tracebacks for 500s. propagate=False keeps them out of root twice.
        "django.request": {"handlers": ["file", "console"], "level": "ERROR", "propagate": False},
    },
}
