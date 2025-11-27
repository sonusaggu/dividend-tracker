# Generated manually

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('portfolio', '0009_portfoliosnapshot'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailVerification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=64, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('is_verified', models.BooleanField(db_index=True, default=False)),
                ('user', models.OneToOneField(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='email_verification', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='emailverification',
            index=models.Index(fields=['token'], name='portfolio_e_token_idx'),
        ),
        migrations.AddIndex(
            model_name='emailverification',
            index=models.Index(fields=['user', 'is_verified'], name='portfolio_e_user_id_verified_idx'),
        ),
    ]


