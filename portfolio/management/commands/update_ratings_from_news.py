"""
Management command to update analyst ratings based on positive news
"""
from django.core.management.base import BaseCommand
from portfolio.utils.rating_updater import update_ratings_for_all_stocks_with_positive_news
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update analyst ratings based on recent positive news sentiment'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days to look back for news (default: 7)'
        )
        parser.add_argument(
            '--min-news',
            type=int,
            default=2,
            help='Minimum number of positive news articles required (default: 2)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each stock'
        )

    def handle(self, *args, **options):
        days = options['days']
        min_news = options['min_news']
        verbose = options['verbose']
        
        self.stdout.write(self.style.SUCCESS(
            f'Updating analyst ratings based on positive news from last {days} days...'
        ))
        
        results = update_ratings_for_all_stocks_with_positive_news(days=days, min_positive_news=min_news)
        
        self.stdout.write(self.style.SUCCESS(
            f'\nSummary:'
        ))
        self.stdout.write(f'  Total stocks with positive news: {results["total_stocks"]}')
        self.stdout.write(self.style.SUCCESS(
            f'  Successfully updated: {results["successful_updates"]}'
        ))
        self.stdout.write(self.style.WARNING(
            f'  Skipped (insufficient news): {results["skipped"]}'
        ))
        if results['failed_updates'] > 0:
            self.stdout.write(self.style.ERROR(
                f'  Failed: {results["failed_updates"]}'
            ))
        
        if verbose and results['messages']:
            self.stdout.write('\nDetailed results:')
            for msg in results['messages']:
                if msg['success']:
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ {msg['stock']}: {msg['message']}"
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"  - {msg['stock']}: {msg['message']}"
                    ))

