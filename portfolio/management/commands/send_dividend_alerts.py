from django.core.management.base import BaseCommand
from django.utils import timezone
from portfolio.models import DividendAlert, Dividend
from datetime import date, datetime
import logging
from collections import defaultdict
from portfolio.utils.email_api import send_dividend_alert_email

logger = logging.getLogger(__name__)

# Try to import pytz, fallback to Django's timezone if not available
try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False
    logger.warning("pytz not available, using Django's timezone utilities")

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
        
        # Get today's date in Toronto timezone
        if HAS_PYTZ:
            toronto_tz = pytz.timezone('America/Toronto')
            today = timezone.now().astimezone(toronto_tz).date()
        else:
            # Use Django's timezone utilities (works with USE_TZ=True)
            # Django's timezone.now() already respects TIME_ZONE setting
            today = timezone.now().date()

        alerts = DividendAlert.objects.filter(is_active=True)\
            .select_related('stock', 'user')

        sent = 0
        skipped = 0
        errors = 0

        # Debug tracking
        total_alerts = alerts.count()
        alerts_by_days_advance = defaultdict(int)
        matched_by_days_advance = defaultdict(int)

        self.stdout.write(f"Checking {total_alerts} active dividend alerts...\n")
        
        # Dump all alerts for debug
        self.stdout.write("Active alerts detail:")
        for alert in alerts:
            self.stdout.write(
                f" - Alert: Stock={alert.stock.symbol}, User={alert.user.email}, days_advance={alert.days_advance}"
            )

        for alert in alerts:
            try:
                stock = alert.stock
                user = alert.user
                alerts_by_days_advance[alert.days_advance] += 1

                # Get upcoming dividend
                dividend = Dividend.objects.filter(
                    stock=stock,
                    ex_dividend_date__gte=today
                ).order_by('ex_dividend_date').first()

                if not dividend:
                    dividend = Dividend.objects.filter(
                        stock=stock,
                        payment_date__gte=today
                    ).order_by('payment_date').first()

                if not dividend:
                    self.stdout.write(self.style.WARNING(
                        f"Skipped {stock.symbol}: No upcoming dividend found for user {user.email}"
                    ))
                    skipped += 1
                    continue

                # Determine dividend date
                raw_date = dividend.ex_dividend_date or dividend.payment_date

                if isinstance(raw_date, datetime):
                    if HAS_PYTZ:
                        dividend_date = raw_date.astimezone(toronto_tz).date() if timezone.is_aware(raw_date) else toronto_tz.localize(raw_date).date()
                    else:
                        # Use Django's timezone utilities
                        if timezone.is_aware(raw_date):
                            dividend_date = timezone.localtime(raw_date).date()
                        else:
                            # Make naive datetime aware, then convert to local time
                            aware_date = timezone.make_aware(raw_date)
                            dividend_date = timezone.localtime(aware_date).date()
                elif isinstance(raw_date, date):
                    dividend_date = raw_date
                else:
                    self.stdout.write(self.style.WARNING(
                        f"Skipped {stock.symbol}: Invalid dividend date for user {user.email}"
                    ))
                    skipped += 1
                    continue

                days_until = (dividend_date - today).days

                # Debug output for each alert/dividend check
                self.stdout.write(
                    f"Checking alert: Stock={stock.symbol}, User={user.email}, "
                    f"days_advance={alert.days_advance}, dividend_date={dividend_date}, "
                    f"today={today}, days_until={days_until}"
                )

                if days_until == alert.days_advance:
                    matched_by_days_advance[alert.days_advance] += 1
                    msg = f"{stock.symbol} -> {user.email} | ${dividend.amount} on {dividend_date}"
                    if dry_run:
                        self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would send: {msg}"))
                    else:
                        send_dividend_alert_email(
                            user_email=user.email,
                            stock_symbol=stock.symbol,
                            dividend_date=dividend_date,
                            days_advance=alert.days_advance,
                            dividend_amount=dividend.amount,
                            dividend_currency=dividend.currency,
                            dividend_frequency=dividend.frequency
                        )
                        self.stdout.write(self.style.SUCCESS(f"Sent: {msg}"))
                        sent += 1
                else:
                    self.stdout.write(
                        f"Skipped alert for {stock.symbol} and user {user.email}: "
                        f"days_until ({days_until}) != days_advance ({alert.days_advance})"
                    )
                    skipped += 1

            except Exception as e:
                errors += 1
                logger.error(f"Error for {alert.stock.symbol} and user {alert.user.email}: {e}")
                self.stdout.write(self.style.ERROR(f"Error: {alert.stock.symbol} -> {e}"))

        # Final summary
        self.stdout.write(self.style.SUCCESS(
            f"\nSummary:\n--------\nTotal Alerts: {total_alerts}\nSent: {sent}\nSkipped: {skipped}\nErrors: {errors}\n"
        ))

        self.stdout.write("Alerts by days_advance:")
        for days, count in sorted(alerts_by_days_advance.items()):
            matched = matched_by_days_advance.get(days, 0)
            self.stdout.write(f"  {days} days: {count} total, {matched} matched today")
