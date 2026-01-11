# Generated migration to fix session_key null constraint
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0017_usersession_websitemetric'),
    ]

    operations = [
        migrations.AlterField(
            model_name='websitemetric',
            name='session_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=40),
        ),
    ]




