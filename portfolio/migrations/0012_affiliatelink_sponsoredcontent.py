# Generated manually

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0011_scrapestatus'),
    ]

    operations = [
        migrations.CreateModel(
            name='AffiliateLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the broker/service', max_length=200)),
                ('platform_type', models.CharField(choices=[('broker', 'Broker'), ('platform', 'Trading Platform'), ('service', 'Financial Service'), ('other', 'Other')], default='broker', max_length=20)),
                ('affiliate_url', models.URLField(help_text='Affiliate/referral link')),
                ('description', models.TextField(blank=True, help_text='Short description')),
                ('logo_url', models.URLField(blank=True, help_text='URL to logo image')),
                ('bonus_offer', models.CharField(blank=True, help_text="e.g., 'Free $50 when you sign up'", max_length=200)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('display_order', models.IntegerField(default=0, help_text='Order for display (lower = first)')),
                ('click_count', models.IntegerField(default=0, help_text='Total clicks tracked')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Affiliate Link',
                'verbose_name_plural': 'Affiliate Links',
                'ordering': ['display_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='SponsoredContent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('content_type', models.CharField(choices=[('featured_stock', 'Featured Stock'), ('educational', 'Educational Content'), ('promotion', 'Promotion'), ('advertisement', 'Advertisement')], default='featured_stock', max_length=20)),
                ('description', models.TextField(help_text='Content description or body')),
                ('image_url', models.URLField(blank=True, help_text='URL to featured image')),
                ('link_url', models.URLField(blank=True, help_text='Optional link URL')),
                ('link_text', models.CharField(blank=True, help_text='Text for the link button', max_length=100)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('display_order', models.IntegerField(default=0, help_text='Order for display (lower = first)')),
                ('start_date', models.DateTimeField(blank=True, help_text='When to start showing', null=True)),
                ('end_date', models.DateTimeField(blank=True, help_text='When to stop showing', null=True)),
                ('view_count', models.IntegerField(default=0)),
                ('click_count', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('stock', models.ForeignKey(blank=True, help_text="If content type is 'featured_stock', select a stock", null=True, on_delete=django.db.models.deletion.SET_NULL, to='portfolio.stock')),
            ],
            options={
                'verbose_name': 'Sponsored Content',
                'verbose_name_plural': 'Sponsored Content',
                'ordering': ['display_order', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='sponsoredcontent',
            index=models.Index(fields=['is_active', 'display_order'], name='portfolio_sp_is_acti_idx'),
        ),
        migrations.AddIndex(
            model_name='sponsoredcontent',
            index=models.Index(fields=['content_type'], name='portfolio_sp_content_idx'),
        ),
        migrations.AddIndex(
            model_name='sponsoredcontent',
            index=models.Index(fields=['start_date', 'end_date'], name='portfolio_sp_start_d_idx'),
        ),
        migrations.AddIndex(
            model_name='affiliatelink',
            index=models.Index(fields=['is_active', 'display_order'], name='portfolio_af_is_acti_idx'),
        ),
        migrations.AddIndex(
            model_name='affiliatelink',
            index=models.Index(fields=['platform_type'], name='portfolio_af_platfor_idx'),
        ),
    ]




