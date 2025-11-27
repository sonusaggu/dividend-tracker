"""
Django management command to clean up old news articles
Helps optimize database by removing news older than specified retention period
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from portfolio.models import StockNews
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up old news articles to optimize database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Keep news articles from the last N days (default: 30)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--keep-per-stock',
            type=int,
            default=50,
            help='Keep at least N most recent articles per stock (default: 50)',
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        keep_per_stock = options['keep_per_stock']
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        self.stdout.write(f"Cleaning up news articles older than {days} days...")
        self.stdout.write(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No articles will be deleted"))
        
        # Strategy 1: Delete articles older than cutoff date
        old_articles = StockNews.objects.filter(
            published_at__lt=cutoff_date
        )
        
        old_count = old_articles.count()
        
        if old_count > 0:
            self.stdout.write(f"\nFound {old_count} articles older than {days} days")
            
            if not dry_run:
                deleted = old_articles.delete()[0]
                self.stdout.write(
                    self.style.SUCCESS(f'Deleted {deleted} old news articles')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Would delete {old_count} old news articles')
                )
        else:
            self.stdout.write(self.style.SUCCESS(f'No articles older than {days} days found'))
        
        # Strategy 2: For each stock, keep only the most recent N articles
        # This ensures we don't accumulate too many articles per stock
        from django.db.models import Count
        from portfolio.models import Stock
        
        stocks_with_excess = Stock.objects.annotate(
            news_count=Count('news')
        ).filter(news_count__gt=keep_per_stock)
        
        if stocks_with_excess.exists():
            self.stdout.write(f"\nFound {stocks_with_excess.count()} stocks with more than {keep_per_stock} articles")
            
            total_excess_deleted = 0
            for stock in stocks_with_excess:
                # Get all news for this stock, ordered by date
                all_news = StockNews.objects.filter(stock=stock).order_by('-published_at')
                total_count = all_news.count()
                
                if total_count > keep_per_stock:
                    # Keep the most recent N articles
                    news_to_keep = all_news[:keep_per_stock]
                    keep_ids = set(news_to_keep.values_list('id', flat=True))
                    
                    # Delete the rest
                    excess_news = all_news.exclude(id__in=keep_ids)
                    excess_count = excess_news.count()
                    
                    if excess_count > 0:
                        if not dry_run:
                            deleted = excess_news.delete()[0]
                            total_excess_deleted += deleted
                            self.stdout.write(
                                f"  {stock.symbol}: Kept {keep_per_stock}, deleted {deleted} excess articles"
                            )
                        else:
                            self.stdout.write(
                                f"  {stock.symbol}: Would keep {keep_per_stock}, would delete {excess_count} excess articles"
                            )
            
            if not dry_run and total_excess_deleted > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'\nTotal excess articles deleted: {total_excess_deleted}')
                )
        
        # Show final statistics
        total_news = StockNews.objects.count()
        self.stdout.write(f"\n{'='*50}")
        self.stdout.write(f"Final statistics:")
        self.stdout.write(f"  Total news articles in database: {total_news}")
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS('\nCleanup completed successfully!'))
        else:
            self.stdout.write(self.style.WARNING('\nDry run completed. Use without --dry-run to actually delete.'))



