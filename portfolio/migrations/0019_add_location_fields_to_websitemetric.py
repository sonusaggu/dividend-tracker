# Generated migration to add location fields to WebsiteMetric
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0018_fix_websitemetric_session_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='websitemetric',
            name='city',
            field=models.CharField(blank=True, db_index=True, max_length=100),
        ),
        migrations.AddField(
            model_name='websitemetric',
            name='region',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='websitemetric',
            name='timezone',
            field=models.CharField(blank=True, max_length=50),
        ),
    ]

