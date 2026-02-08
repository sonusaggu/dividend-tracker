# Data migration: ensure default Site exists for sitemaps (SITE_ID = 1)

from django.db import migrations


def create_default_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.get_or_create(
        id=1,
        defaults={"domain": "dividend.forum", "name": "StockFolio"},
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0022_add_show_in_listing_to_stock"),
        ("sites", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_site, noop),
    ]
