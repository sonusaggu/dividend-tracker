# Generated manually

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0010_emailverification'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScrapeStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], db_index=True, default='running', max_length=20)),
                ('started_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('days', models.IntegerField(default=60, help_text='Number of days of historical data to fetch')),
                ('total_stocks', models.IntegerField(default=0, help_text='Total stocks processed')),
                ('success_count', models.IntegerField(default=0, help_text='Successfully updated stocks')),
                ('failed_count', models.IntegerField(default=0, help_text='Failed stocks')),
                ('error_message', models.TextField(blank=True, help_text='Error message if failed', null=True)),
                ('failed_symbols', models.JSONField(blank=True, default=list, help_text='List of failed stock symbols')),
                ('duration_seconds', models.IntegerField(blank=True, help_text='Duration in seconds', null=True)),
                ('notes', models.TextField(blank=True, help_text='Additional notes or details')),
            ],
            options={
                'verbose_name': 'Scrape Status',
                'verbose_name_plural': 'Scrape Statuses',
                'ordering': ['-started_at'],
            },
        ),
        migrations.AddIndex(
            model_name='scrapestatus',
            index=models.Index(fields=['-started_at'], name='portfolio_s_started_idx'),
        ),
        migrations.AddIndex(
            model_name='scrapestatus',
            index=models.Index(fields=['status', '-started_at'], name='portfolio_s_status_idx'),
        ),
    ]




