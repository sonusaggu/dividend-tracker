# Add view_count to Stock so INSERTs satisfy NOT NULL (e.g. scraper batch create).
# Idempotent: only adds the column if it does not already exist.

from django.db import migrations, connection


def add_view_count_if_missing(apps, schema_editor):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'portfolio_stock' AND column_name = 'view_count';
            """
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE portfolio_stock ADD COLUMN view_count INTEGER NOT NULL DEFAULT 0;"
            )


def backfill_view_count_null(apps, schema_editor):
    """Set view_count=0 for any existing rows that have NULL (satisfy NOT NULL)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portfolio_stock SET view_count = 0 WHERE view_count IS NULL;"
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0023_create_default_site'),
    ]

    operations = [
        migrations.RunPython(add_view_count_if_missing, noop),
        migrations.RunPython(backfill_view_count_null, noop),
    ]
