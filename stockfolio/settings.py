import os
from pathlib import Path
from decouple import config  # <-- Add this import
import dj_database_url 

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='ss7g$%z8rkh=3fc8cx0bux(wi(exgq1@35-+*hlf^o2s(2as1w')  # Use environment variable in production
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
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'whitenoise.runserver_nostatic',

    # Your custom apps
    'portfolio',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', 
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
            conn_max_age=0,
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
             'CONN_MAX_AGE': 0,  # Reduced connection lifetime
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

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if DEBUG else []
STATIC_ROOT = BASE_DIR / 'staticfiles'  # For production deployment

# Default primary key type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login/logout redirection settings
LOGIN_REDIRECT_URL = 'dashboard'  # After login, go to dashboard
LOGOUT_REDIRECT_URL = 'home'      # After logout, go to home page

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

# Email configuration with cleaning to remove problematic characters
def clean_email_credential(value):
    """Clean email credentials to remove non-ASCII characters that cause encoding issues"""
    if not value:
        return value
    # Convert to string and strip whitespace
    value = str(value).strip()
    # Remove non-breaking spaces and other problematic characters
    value = value.replace('\xa0', ' ').replace('\u00a0', ' ')
    value = value.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
    value = value.replace('\ufeff', '')
    # Remove any remaining non-ASCII characters that can't be encoded as ASCII
    value = value.encode('ascii', 'ignore').decode('ascii')
    return value.strip()

EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = clean_email_credential(config('EMAIL_HOST_USER', default=''))
EMAIL_HOST_PASSWORD = clean_email_credential(config('EMAIL_HOST_PASSWORD', default=''))
DEFAULT_FROM_EMAIL = clean_email_credential(config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER))