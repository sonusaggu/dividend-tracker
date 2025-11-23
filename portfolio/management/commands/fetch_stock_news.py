"""
Django management command to fetch news for stocks
Can be run for all stocks, portfolio stocks, or watchlist stocks
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from portfolio.models import Stock, UserPortfolio, Watchlist
from portfolio.utils.news_fetcher import NewsFetcher
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fetch news articles for stocks'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Fetch news for a specific user\'s portfolio and watchlist',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Fetch news for all stocks in database',
        )
        parser.add_argument(
            '--portfolio-only',
            action='store_true',
            help='Fetch news only for portfolio stocks',
        )
        parser.add_argument(
            '--watchlist-only',
            action='store_true',
            help='Fetch news only for watchlist stocks',
        )
        parser.add_argument(
            '--max-articles',
            type=int,
            default=10,
            help='Maximum articles to fetch per stock (default: 10)',
        )
        parser.add_argument(
            '--max-stocks',
            type=int,
            default=100,
            help='Maximum stocks to process (default: 100)',
        )
        parser.add_argument(
            '--skip-cleanup',
            action='store_true',
            help='Skip automatic cleanup after fetching',
        )
        parser.add_argument(
            '--cleanup-days',
            type=int,
            default=30,
            help='Days to keep news articles (default: 30)',
        )
        parser.add_argument(
            '--cleanup-keep-per-stock',
            type=int,
            default=50,
            help='Keep N most recent articles per stock (default: 50)',
        )

    def handle(self, *args, **options):
        fetcher = NewsFetcher()
        
        # Determine which stocks to fetch news for
        if options['user']:
            # Fetch for specific user's portfolio and watchlist
            try:
                user = User.objects.get(username=options['user'])
                portfolio_stocks = Stock.objects.filter(
                    userportfolio__user=user
                ).distinct()
                watchlist_stocks = Stock.objects.filter(
                    watchlist__user=user
                ).distinct()
                stocks = (portfolio_stocks | watchlist_stocks).distinct()[:options['max_stocks']]
                self.stdout.write(f"Fetching news for user {user.username}'s stocks...")
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User '{options['user']}' not found"))
                return
        elif options['portfolio_only']:
            # Fetch for all portfolio stocks
            stocks = Stock.objects.filter(
                userportfolio__isnull=False
            ).distinct()[:options['max_stocks']]
            self.stdout.write("Fetching news for all portfolio stocks...")
        elif options['watchlist_only']:
            # Fetch for all watchlist stocks
            stocks = Stock.objects.filter(
                watchlist__isnull=False
            ).distinct()[:options['max_stocks']]
            self.stdout.write("Fetching news for all watchlist stocks...")
        elif options['all']:
            # Fetch for all stocks
            stocks = Stock.objects.all()[:options['max_stocks']]
            self.stdout.write(f"Fetching news for all stocks (limited to {options['max_stocks']})...")
        else:
            # Default: fetch for stocks that have portfolio or watchlist entries
            portfolio_stocks = Stock.objects.filter(
                userportfolio__isnull=False
            ).distinct()
            watchlist_stocks = Stock.objects.filter(
                watchlist__isnull=False
            ).distinct()
            stocks = (portfolio_stocks | watchlist_stocks).distinct()[:options['max_stocks']]
            self.stdout.write("Fetching news for portfolio and watchlist stocks...")
        
        if not stocks.exists():
            self.stdout.write(self.style.WARNING("No stocks found to fetch news for"))
            return
        
        self.stdout.write(f"Processing {stocks.count()} stocks...")
        
        # Fetch and save news
        total_saved = fetcher.fetch_and_save_news(
            stocks,
            max_articles_per_stock=options['max_articles'],
            max_age_days=7
        )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully fetched and saved {total_saved} news articles for {stocks.count()} stocks'
            )
        )
        
        # Auto-cleanup old news after fetching (unless --skip-cleanup is specified)
        if not options['skip_cleanup']:
            from portfolio.models import StockNews
            
            self.stdout.write("\nRunning automatic cleanup of old news...")
            deleted, remaining = StockNews.cleanup_old_news(
                days=options['cleanup_days'],
                keep_per_stock=options['cleanup_keep_per_stock']
            )
            
            if deleted > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Cleaned up {deleted} old news articles. {remaining} articles remaining.'
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ No old news to clean up. {remaining} articles in database.'
                    )
                )

