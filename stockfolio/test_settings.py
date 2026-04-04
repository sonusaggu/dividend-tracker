"""
Test settings — overrides the database with SQLite so tests run locally
without needing a PostgreSQL server. Used via:
    python manage.py test --settings=stockfolio.test_settings
"""
from stockfolio.settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Speed up password hashing in tests
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Silence email sending — tests don't need real SMTP/Resend
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
