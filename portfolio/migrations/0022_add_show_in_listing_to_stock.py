# Generated migration for show_in_listing field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0021_earnings_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='stock',
            name='show_in_listing',
            field=models.BooleanField(db_index=True, default=True, help_text="If False, stock won't appear in all stocks page"),
        ),
    ]

