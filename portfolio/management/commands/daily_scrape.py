from django.core.management.base import BaseCommand
from portfolio.utils.scraper import TSXScraper
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
    
    def handle(self, *args, **options):
        days = options['days']
        
        self.stdout.write(f"🚀 Starting daily stock scrape for {days} days...")
        logger.info(f"🚀 Starting daily stock scrape for {days} days...")
        
        scraper = TSXScraper()
        results = scraper.update_daily_stocks(days=days)
        
        success_count = sum(1 for r in results if r['success'])
        failed_count = len(results) - success_count
        
        self.stdout.write(
            self.style.SUCCESS(f"✅ Daily scrape completed: {success_count}/{len(results)} stocks updated")
        )
        logger.info(f"✅ Daily scrape completed: {success_count} successful, {failed_count} failed out of {len(results)} total stocks")
        
        # Log summary
        if failed_count > 0:
            failed_symbols = [r['symbol'] for r in results if not r['success']]
            logger.warning(f"⚠️ Failed to update {failed_count} stocks: {failed_symbols[:10]}")  # Log first 10