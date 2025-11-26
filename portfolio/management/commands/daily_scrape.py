from django.core.management.base import BaseCommand
from portfolio.utils.scraper import TSXScraper
from portfolio.models import ScrapeStatus
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run daily stock scraping'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=60,
            help='Number of days of historical data to fetch (default: 60)',
        )
        parser.add_argument(
            '--status-id',
            type=int,
            default=None,
            help='Existing ScrapeStatus ID to update (optional)',
        )
    
    def handle(self, *args, **options):
        days = options['days']
        status_id = options.get('status_id')
        
        # Get or create scrape status
        if status_id:
            try:
                scrape_status = ScrapeStatus.objects.get(id=status_id)
            except ScrapeStatus.DoesNotExist:
                scrape_status = ScrapeStatus.create_new(days=days)
                logger.warning(f"Status ID {status_id} not found, created new status {scrape_status.id}")
        else:
            scrape_status = ScrapeStatus.create_new(days=days)
        
        self.stdout.write(f"🚀 Starting daily stock scrape for {days} days...")
        self.stdout.write(f"📊 Status ID: {scrape_status.id}")
        logger.info(f"🚀 Starting daily stock scrape for {days} days (Status ID: {scrape_status.id})...")
        self.stdout.write("⏳ This may take a few minutes. Progress will be shown below...")
        self.stdout.write("")
        
        try:
            scraper = TSXScraper()
            results = scraper.update_daily_stocks(days=days)
            
            success_count = sum(1 for r in results if r['success'])
            failed_count = len(results) - success_count
            total_stocks = len(results)
            failed_symbols = [r.get('symbol', 'Unknown') for r in results if not r['success']]
            
            # Update status in database
            notes = f"Scrape completed: {success_count} successful, {failed_count} failed out of {total_stocks} total stocks"
            scrape_status.mark_completed(
                success_count=success_count,
                failed_count=failed_count,
                total_stocks=total_stocks,
                failed_symbols=failed_symbols,
                notes=notes
            )
            
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(f"✅ Daily scrape completed: {success_count}/{total_stocks} stocks updated")
            )
            logger.info(f"✅ Daily scrape completed: {success_count} successful, {failed_count} failed out of {total_stocks} total stocks (Status ID: {scrape_status.id})")
            
            # Log summary
            if failed_count > 0:
                self.stdout.write(
                    self.style.WARNING(f"⚠️  Failed to update {failed_count} stocks: {', '.join(failed_symbols[:10])}")
                )
                logger.warning(f"⚠️ Failed to update {failed_count} stocks: {failed_symbols[:10]}")
            else:
                self.stdout.write(self.style.SUCCESS("✨ All stocks processed successfully!"))
            
            self.stdout.write(f"📊 Status saved to database (ID: {scrape_status.id})")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Error in daily scrape: {error_msg}")
            scrape_status.mark_failed(error_message=error_msg, notes=f"Scrape failed with error: {error_msg}")
            self.stdout.write(self.style.ERROR(f"❌ Scrape failed: {error_msg}"))
            self.stdout.write(f"📊 Status saved to database (ID: {scrape_status.id})")
            raise