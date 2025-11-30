# Generated migration for StockNote model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('portfolio', '0013_social_features'),
    ]

    operations = [
        migrations.CreateModel(
            name='StockNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('note_type', models.CharField(choices=[('note', 'Quick Note'), ('research', 'Research'), ('journal', 'Journal Entry'), ('buy', 'Buy Decision'), ('sell', 'Sell Decision'), ('watch', 'Watch'), ('analysis', 'Analysis')], db_index=True, default='note', max_length=20)),
                ('title', models.CharField(blank=True, help_text='Optional title for the note', max_length=200)),
                ('content', models.TextField(help_text='Note content')),
                ('tags', models.CharField(blank=True, help_text='Comma-separated tags (buy, sell, research, etc.)', max_length=200)),
                ('is_private', models.BooleanField(default=True, help_text='Private notes are only visible to you')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('stock', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='portfolio.stock')),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='stock_notes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Stock Note',
                'verbose_name_plural': 'Stock Notes',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='stocknote',
            index=models.Index(fields=['user', '-created_at'], name='portfolio_s_user_id_idx'),
        ),
        migrations.AddIndex(
            model_name='stocknote',
            index=models.Index(fields=['stock', '-created_at'], name='portfolio_s_stock_i_idx'),
        ),
        migrations.AddIndex(
            model_name='stocknote',
            index=models.Index(fields=['user', 'stock', '-created_at'], name='portfolio_s_user_id_stock_idx'),
        ),
        migrations.AddIndex(
            model_name='stocknote',
            index=models.Index(fields=['note_type', '-created_at'], name='portfolio_s_note_ty_idx'),
        ),
    ]




