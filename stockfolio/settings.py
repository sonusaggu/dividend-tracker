import os
from pathlib import Path
from decouple import config  # <-- Add this import
import dj_database_url
import logging

logger = logging.getLogger(__name__) 

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='SECRET_KEY=ss7g$%z8rkh=3fc8cx0bux(wi(exgq1@35-+*hlf^o2s(2as1w')
DIVIDEND_ALERT_SECRET = config('DIVIDEND_ALERT_SECRET', default=SECRET_KEY)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = ['localhost', '127.0.0.1','.onrender.com', 'dividend.forum']

RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',             # Admin panel
    'django.contrib.auth',              # Authentication system
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.sites',              # Required for sitemaps (domain)
    'django.contrib.sitemaps',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'whitenoise.runserver_nostatic',

    # Your custom apps
    'portfolio',
]

# Sitemaps: used by django.contrib.sitemaps (set your domain in Admin > Sites)
SITE_ID = 1

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'portfolio.middleware.BlockSuspiciousUserAgentsMiddleware',  # Block security scanners
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'portfolio.middleware.SecurityHeadersMiddleware',  # Add security headers
    'portfolio.middleware.DatabaseErrorHandlerMiddleware',  # Handle database errors gracefully
    # 'portfolio.middleware.WebsiteMetricsMiddleware',  # Disabled for performance - can be re-enabled if needed
]

# Main URL config
ROOT_URLCONF = 'stockfolio.urls'

# Templates configuration
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            # Add any template directories here if needed
            BASE_DIR / 'templates',
        ],
        'APP_DIRS': True,  # This should be True for admin to work
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# WSGI application
WSGI_APPLICATION = 'stockfolio.wsgi.application'

# PostgreSQL database settings (use docker-compose env vars or fallback defaults)
database_url = config('DATABASE_URL', default=None)

if database_url:
    # Use DATABASE_URL if available (Render production)
    DATABASES = {
        'default': dj_database_url.config(
            conn_max_age=600,  # Keep connections alive for 10 minutes (reduces connection overhead)
            ssl_require=not DEBUG
        )
    }
else:
    # Fallback to individual variables (local development)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='stockfolio_db'),
            'USER': config('DB_USER', default='stockfolio_user'),
            'PASSWORD': config('DB_PASSWORD', default='stockfolio_pass'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
            'CONN_MAX_AGE': 600,  # Keep connections alive for 10 minutes (reduces connection overhead)
            'OPTIONS': {
                'connect_timeout': 10,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            }
        }
    }

# Password validators
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

# Localization settings
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Toronto'
USE_I18N = True
USE_TZ = True

# Static files (put files in stockfolio/static/ and access at /static/...)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']  # Always include so collectstatic picks it up
STATIC_ROOT = BASE_DIR / 'staticfiles'  # For production deployment

# WhiteNoise configuration for serving static files in production
# When DEBUG=False, WhiteNoise will serve static files including admin static files
# IMPORTANT: Run 'python manage.py collectstatic --noinput' after setting DEBUG=False
if not DEBUG:
    # Use WhiteNoise for static file serving in production
    # CompressedManifestStaticFilesStorage provides compression and cache busting
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    # In production, serve from collected static files (not finders)
    # This is more efficient and ensures all files are available
    WHITENOISE_USE_FINDERS = False
    # Don't auto-refresh in production (better performance)
    WHITENOISE_AUTOREFRESH = False
else:
    # In development, use default storage
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# Default primary key type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Cache configuration
# Using local memory cache (fast, but lost on restart)
# For production with multiple workers, use Redis:
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#         'LOCATION': 'redis://127.0.0.1:6379/1',
#     }
# }
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
        'OPTIONS': {
            'MAX_ENTRIES': 10000,
        },
        'TIMEOUT': 300,  # Default cache timeout: 5 minutes
    }
}

# Login/logout redirection settings
LOGIN_URL = '/login/'  # URL to redirect to when login is required
LOGIN_REDIRECT_URL = 'dashboard'  # After login, go to dashboard
LOGOUT_REDIRECT_URL = 'home'      # After logout, go to home page

# Custom authentication backends - allow login with email or username
AUTHENTICATION_BACKENDS = [
    'portfolio.backends.EmailOrUsernameBackend',  # Custom backend for email/username login
    'django.contrib.auth.backends.ModelBackend',  # Default backend (fallback)
]

# File upload settings - optimized for Render server (30 second timeout)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB (reduced for Render timeout limits)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB (reduced for Render timeout limits)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000  # Reduced field limit for Render server

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Security headers for all environments
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'

# Email configuration with cleaning to remove problematic characters
def clean_email_credential(value):
    """Clean email credentials to remove non-ASCII characters that cause encoding issues"""
    if not value:
        return value or ''
    # Convert to string and strip whitespace
    value = str(value).strip()
    if not value:
        return ''
    # Remove non-breaking spaces and other problematic characters
    value = value.replace('\xa0', ' ').replace('\u00a0', ' ')
    value = value.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
    value = value.replace('\ufeff', '')
    # Remove any remaining non-ASCII characters that can't be encoded as ASCII
    value = value.encode('ascii', 'ignore').decode('ascii')
    result = value.strip()
    return result if result else ''

# Resend API Configuration
RESEND_API_KEY = config('RESEND_API_KEY', default='')
RESEND_FROM_EMAIL = config('RESEND_FROM_EMAIL', default='')
USE_RESEND = bool(RESEND_API_KEY and RESEND_FROM_EMAIL)

# Email backend - use Resend if configured, otherwise use SMTP
if USE_RESEND:
    EMAIL_BACKEND = 'portfolio.utils.email_backend.ResendEmailBackend'
    logger.info("Using Resend email backend")
else:
    EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = clean_email_credential(config('EMAIL_HOST_USER', default=''))
EMAIL_HOST_PASSWORD = clean_email_credential(config('EMAIL_HOST_PASSWORD', default=''))

# Set DEFAULT_FROM_EMAIL - ensure it's never empty
# Priority: 1) DEFAULT_FROM_EMAIL env var, 2) EMAIL_HOST_USER, 3) fallback default
default_from_email_env = config('DEFAULT_FROM_EMAIL', default='')
DEFAULT_FROM_EMAIL = None

if default_from_email_env and default_from_email_env.strip():
    cleaned = clean_email_credential(default_from_email_env)
    if cleaned and cleaned.strip():
        DEFAULT_FROM_EMAIL = cleaned

if not DEFAULT_FROM_EMAIL and EMAIL_HOST_USER and EMAIL_HOST_USER.strip():
    cleaned = clean_email_credential(EMAIL_HOST_USER)
    if cleaned and cleaned.strip():
        DEFAULT_FROM_EMAIL = cleaned

# Final fallback - ensure DEFAULT_FROM_EMAIL is never empty
if not DEFAULT_FROM_EMAIL or not DEFAULT_FROM_EMAIL.strip():
    DEFAULT_FROM_EMAIL = 'noreply@dividend.forum'

# Contact form recipient email (defaults to DEFAULT_FROM_EMAIL if not set)
CONTACT_EMAIL = config('CONTACT_EMAIL', default=DEFAULT_FROM_EMAIL)

# Site domain for password reset emails and verification links
# Priority: 1. Environment variable, 2. dividend.forum, 3. Render hostname, 4. localhost
SITE_DOMAIN = config('SITE_DOMAIN', default=None)
if not SITE_DOMAIN:
    if 'dividend.forum' in ALLOWED_HOSTS:
        SITE_DOMAIN = "https://dividend.forum"
    elif RENDER_EXTERNAL_HOSTNAME:
        SITE_DOMAIN = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    else:
        SITE_DOMAIN = 'http://localhost:8000'

# Logging configuration - ensures logs appear in Render
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name} {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '[{levelname}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'portfolio': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'portfolio.utils.email_service': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'portfolio.utils.email_verification': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}