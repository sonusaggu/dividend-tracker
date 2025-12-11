# Generated migration for Stock Tags and Watchlist Groups

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('portfolio', '0019_add_location_fields_to_websitemetric'),
    ]

    operations = [
        migrations.CreateModel(
            name='WatchlistGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('color', models.CharField(default='#3B82F6', help_text='Hex color code for the group', max_length=7)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('order', models.IntegerField(default=0, help_text='Order for displaying groups')),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='watchlist_groups', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['order', 'name'],
                'unique_together': {('user', 'name')},
            },
        ),
        migrations.CreateModel(
            name='StockTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('color', models.CharField(default='#6B7280', help_text='Hex color code for the tag', max_length=7)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='stock_tags', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
                'unique_together': {('user', 'name')},
            },
        ),
        migrations.AddField(
            model_name='watchlist',
            name='group',
            field=models.ForeignKey(blank=True, db_index=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='watchlist_items', to='portfolio.watchlistgroup'),
        ),
        migrations.CreateModel(
            name='TaggedStock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('stock', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='tags', to='portfolio.stock')),
                ('tag', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='tagged_stocks', to='portfolio.stocktag')),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('tag', 'stock')},
            },
        ),
        migrations.AddIndex(
            model_name='watchlistgroup',
            index=models.Index(fields=['user', 'order'], name='portfolio_w_user_id_order_idx'),
        ),
        migrations.AddIndex(
            model_name='stocktag',
            index=models.Index(fields=['user', 'name'], name='portfolio_s_user_id_name_idx'),
        ),
        migrations.AddIndex(
            model_name='watchlist',
            index=models.Index(fields=['user', 'group'], name='portfolio_w_user_id_group_idx'),
        ),
        migrations.AddIndex(
            model_name='taggedstock',
            index=models.Index(fields=['tag', 'stock'], name='portfolio_t_tag_id_stock_idx'),
        ),
        migrations.AddIndex(
            model_name='taggedstock',
            index=models.Index(fields=['stock'], name='portfolio_t_stock_id_idx'),
        ),
    ]

