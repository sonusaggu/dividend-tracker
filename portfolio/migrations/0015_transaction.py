# Generated migration for Transaction model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('portfolio', '0014_stocknote'),
    ]

    operations = [
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(choices=[('BUY', 'Buy'), ('SELL', 'Sell'), ('DIVIDEND', 'Dividend Reinvestment'), ('SPLIT', 'Stock Split'), ('MERGER', 'Merger/Acquisition')], db_index=True, max_length=10)),
                ('transaction_date', models.DateField(db_index=True)),
                ('shares', models.DecimalField(decimal_places=6, max_digits=12)),
                ('price_per_share', models.DecimalField(decimal_places=4, max_digits=10)),
                ('fees', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('total_amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('notes', models.TextField(blank=True)),
                ('cost_basis_method', models.CharField(choices=[('FIFO', 'First In First Out'), ('LIFO', 'Last In First Out'), ('AVERAGE', 'Average Cost')], default='FIFO', max_length=10)),
                ('realized_gain_loss', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('is_processed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('stock', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='portfolio.stock')),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-transaction_date', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['user', 'stock', '-transaction_date'], name='portfolio_t_user_id_idx'),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['user', '-transaction_date'], name='portfolio_t_user_id_2_idx'),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['transaction_type', 'transaction_date'], name='portfolio_t_transac_idx'),
        ),
    ]



