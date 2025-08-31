#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Collect static files
python manage.py collectstatic --no-input

python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='stockfolio_user').exists():
    User.objects.create_superuser(
        username='stockfolio_user',
        email='admin@example.com',
        password='stockfolio_pass'
    )
END

# Apply database migrations
python manage.py migrate