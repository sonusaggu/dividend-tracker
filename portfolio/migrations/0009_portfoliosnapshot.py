# Generated manually
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0008_stocknews'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='PortfolioSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('snapshot_date', models.DateField(db_index=True)),
                ('total_value', models.DecimalField(decimal_places=2, max_digits=12)),
                ('total_investment', models.DecimalField(decimal_places=2, max_digits=12)),
                ('total_gain_loss', models.DecimalField(decimal_places=2, max_digits=12)),
                ('total_roi_percent', models.DecimalField(decimal_places=4, max_digits=8)),
                ('annual_dividend_income', models.DecimalField(decimal_places=2, max_digits=12)),
                ('dividend_yield', models.DecimalField(decimal_places=3, max_digits=6)),
                ('total_holdings', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='portfolio_snapshots', to='auth.user')),
            ],
            options={
                'ordering': ['-snapshot_date'],
            },
        ),
        migrations.AddIndex(
            model_name='portfoliosnapshot',
            index=models.Index(fields=['user', '-snapshot_date'], name='portfolio_p_user_id_idx'),
        ),
        migrations.AddIndex(
            model_name='portfoliosnapshot',
            index=models.Index(fields=['snapshot_date'], name='portfolio_p_snapsho_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='portfoliosnapshot',
            unique_together={('user', 'snapshot_date')},
        ),
    ]


