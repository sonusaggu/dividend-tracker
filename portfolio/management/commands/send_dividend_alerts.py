from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from portfolio.models import DividendAlert, Dividend
from portfolio.email import send_dividend_alert_email
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Send dividend alert emails to users'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Test run without sending actual emails',
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()
        
        # Get active alerts and prefetch related data
        alerts = DividendAlert.objects.filter(
            is_active=True
        ).select_related('stock', 'user').prefetch_related('stock__dividends')
        
        sent_count = 0
        error_count = 0
        skipped_count = 0
        
        self.stdout.write(f"Checking {alerts.count()} active dividend alerts...")
        
        for alert in alerts:
            try:
                stock = alert.stock
                
                # Get the most recent upcoming dividend for this stock
                upcoming_dividend = Dividend.objects.filter(
                    stock=stock,
                    ex_dividend_date__gte=today  # Future ex-dividend dates
                ).order_by('ex_dividend_date').first()
                
                if not upcoming_dividend:
                    # Try payment date if no ex-dividend date
                    upcoming_dividend = Dividend.objects.filter(
                        stock=stock,
                        payment_date__gte=today  # Future payment dates
                    ).order_by('payment_date').first()
                
                if not upcoming_dividend:
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped {stock.symbol}: No upcoming dividend found"
                        )
                    )
                    continue
                
                # Use ex_dividend_date if available, otherwise payment_date
                dividend_date = upcoming_dividend.ex_dividend_date or upcoming_dividend.payment_date
                
                if not dividend_date:
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped {stock.symbol}: No valid dividend date"
                        )
                    )
                    continue
                
                days_until_dividend = (dividend_date - today).days
                
                # Check if alert should be sent today
                if days_until_dividend == alert.days_advance:
                    if dry_run:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"[DRY RUN] Would send alert for {stock.symbol} to {alert.user.email}"
                                f" - Dividend: ${upcoming_dividend.amount} on {dividend_date}"
                            )
                        )
                    else:
                        send_dividend_alert_email(
                            user_email=alert.user.email,
                            stock_symbol=stock.symbol,
                            dividend_date=dividend_date,
                            days_advance=alert.days_advance,
                            dividend_amount=upcoming_dividend.amount,
                            dividend_currency=upcoming_dividend.currency,
                            dividend_frequency=upcoming_dividend.frequency
                        )
                        sent_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Sent alert for {stock.symbol} to {alert.user.email}"
                                f" - ${upcoming_dividend.amount} on {dividend_date}"
                            )
                        )
                else:
                    skipped_count += 1
                        
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing alert for {alert.stock.symbol}: {e}")
                self.stdout.write(
                    self.style.ERROR(
                        f"Error processing {alert.stock.symbol}: {e}"
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed: {sent_count} alerts sent, {error_count} errors, {skipped_count} skipped"
            )
        )