"""
Django management command to fetch earnings data
Can be run for all stocks, portfolio stocks, watchlist stocks, or specific symbols
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from portfolio.models import Stock, UserPortfolio, Watchlist, Earnings
from portfolio.utils.earnings_fetcher import EarningsFetcher
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fetch earnings calendar and earnings data for stocks'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days ahead to fetch earnings (default: 30)',
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Fetch earnings for a specific user\'s portfolio and watchlist',
        )
        parser.add_argument(
            '--symbol',
            type=str,
            help='Fetch earnings for a specific stock symbol',
        )
        parser.add_argument(
            '--portfolio-only',
            action='store_true',
            help='Fetch earnings only for portfolio stocks',
        )
        parser.add_argument(
            '--watchlist-only',
            action='store_true',
            help='Fetch earnings only for watchlist stocks',
        )
        parser.add_argument(
            '--all-stocks',
            action='store_true',
            help='Fetch earnings calendar for all stocks (may take longer)',
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing earnings records if found',
        )

    def handle(self, *args, **options):
        fetcher = EarningsFetcher()
        days = options['days']
        today = timezone.now().date()
        end_date = today + timedelta(days=days)
        
        self.stdout.write(self.style.SUCCESS(
            f'📊 Fetching earnings data from {today} to {end_date}...'
        ))
        
        # Determine which stocks to fetch earnings for
        stocks_to_fetch = None
        fetch_calendar = True
        
        if options['symbol']:
            # Fetch for specific symbol
            try:
                stock = Stock.objects.get(symbol=options['symbol'].upper())
                stocks_to_fetch = [stock]
                fetch_calendar = False  # Fetch specific stock earnings history
                self.stdout.write(f'Fetching earnings history for {stock.symbol}...')
            except Stock.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f'Stock {options["symbol"]} not found in database'
                ))
                return
        
        elif options['user']:
            # Fetch for specific user's portfolio and watchlist
            try:
                user = User.objects.get(username=options['user'])
                portfolio_stocks = Stock.objects.filter(
                    userportfolio__user=user
                ).distinct()
                watchlist_stocks = Stock.objects.filter(
                    watchlist__user=user
                ).distinct()
                
                if options['portfolio_only']:
                    stocks_to_fetch = list(portfolio_stocks)
                    self.stdout.write(f'Fetching earnings for {user.username}\'s portfolio stocks...')
                elif options['watchlist_only']:
                    stocks_to_fetch = list(watchlist_stocks)
                    self.stdout.write(f'Fetching earnings for {user.username}\'s watchlist stocks...')
                else:
                    stocks_to_fetch = list((portfolio_stocks | watchlist_stocks).distinct())
                    self.stdout.write(f'Fetching earnings for {user.username}\'s portfolio and watchlist stocks...')
                
                if not stocks_to_fetch:
                    self.stdout.write(self.style.WARNING(
                        f'No stocks found for user {user.username}'
                    ))
                    return
                
                self.stdout.write(f'Found {len(stocks_to_fetch)} stock(s) to process')
                fetch_calendar = False  # Fetch specific stock earnings
                
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f'User {options["user"]} not found'
                ))
                return
        
        elif options['all_stocks']:
            # Fetch earnings calendar for Canadian stocks only
            self.stdout.write('Fetching earnings calendar for Canadian (TSX) stocks only...')
            stocks_to_fetch = None
            fetch_calendar = True
        
        # Fetch earnings data
        total_fetched = 0
        total_created = 0
        total_updated = 0
        errors = []
        
        if fetch_calendar:
            # Fetch earnings calendar (Canadian stocks only)
            try:
                self.stdout.write('Fetching earnings calendar from API (Canadian stocks only)...')
                earnings_data = fetcher.fetch_earnings_calendar(
                    start_date=today,
                    end_date=end_date,
                    canadian_only=True  # Only Canadian stocks
                )
                
                if earnings_data:
                    self.stdout.write(f'Received {len(earnings_data)} earnings events from API')
                    
                    for earning_data in earnings_data:
                        symbol = earning_data.get('symbol', '').upper()
                        if not symbol:
                            continue
                        
                        try:
                            company_name = earning_data.get('company_name', symbol)
                            
                            # Get or create stock (create if doesn't exist)
                            stock, stock_created = Stock.objects.get_or_create(
                                symbol=symbol,
                                defaults={
                                    'code': symbol,
                                    'company_name': company_name,
                                    'show_in_listing': False,  # Hide from all stocks page
                                    'sector': '',
                                    'industry': '',
                                }
                            )
                            
                            # Create default dividend with 0 amount if stock was just created
                            if stock_created:
                                from portfolio.models import Dividend
                                if not Dividend.objects.filter(stock=stock).exists():
                                    # Use a far future date to avoid unique constraint issues
                                    Dividend.objects.create(
                                        stock=stock,
                                        amount=0,
                                        currency='CAD',
                                        yield_percent=0,
                                        frequency='Unknown',
                                        ex_dividend_date=end_date + timedelta(days=365*10),  # Far future date
                                    )
                                self.stdout.write(f'  Created stock {symbol} (hidden from all stocks page)')
                            
                            earnings_date = earning_data.get('date')
                            
                            if earnings_date:
                                earnings_obj, created = Earnings.objects.get_or_create(
                                    stock=stock,
                                    earnings_date=earnings_date,
                                    defaults={
                                        'time': earning_data.get('time', ''),
                                        'eps_estimate': earning_data.get('eps_estimate'),
                                        'eps_actual': earning_data.get('eps_actual'),
                                        'revenue_estimate': earning_data.get('revenue_estimate'),
                                        'revenue_actual': earning_data.get('revenue_actual'),
                                        'source': earning_data.get('source', 'api')
                                    }
                                )
                                
                                if created:
                                    total_created += 1
                                elif options['update_existing']:
                                    # Update existing record
                                    earnings_obj.time = earning_data.get('time', earnings_obj.time)
                                    earnings_obj.eps_estimate = earning_data.get('eps_estimate') or earnings_obj.eps_estimate
                                    earnings_obj.eps_actual = earning_data.get('eps_actual') or earnings_obj.eps_actual
                                    earnings_obj.revenue_estimate = earning_data.get('revenue_estimate') or earnings_obj.revenue_estimate
                                    earnings_obj.revenue_actual = earning_data.get('revenue_actual') or earnings_obj.revenue_actual
                                    earnings_obj.source = earning_data.get('source', earnings_obj.source)
                                    earnings_obj.save()
                                    total_updated += 1
                                
                                total_fetched += 1
                                
                                if total_fetched % 10 == 0:
                                    self.stdout.write(f'  Processed {total_fetched} earnings events...')
                        
                        except Exception as e:
                            errors.append(f'Error processing {earning_data.get("symbol", "unknown")}: {str(e)}')
                            logger.error(f'Error processing earnings for {earning_data.get("symbol", "unknown")}: {e}')
                            continue
                else:
                    self.stdout.write(self.style.WARNING(
                        'No earnings data received from API'
                    ))
            
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Error fetching earnings calendar: {str(e)}'
                ))
                logger.error(f'Error fetching earnings calendar: {e}')
                return
        
        else:
            # Fetch earnings for specific stocks
            if stocks_to_fetch:
                for stock in stocks_to_fetch:
                    try:
                        self.stdout.write(f'Fetching earnings for {stock.symbol}...')
                        earnings_data = fetcher.fetch_stock_earnings(stock.symbol)
                        
                        if earnings_data:
                            for earning_data in earnings_data:
                                earnings_date = earning_data.get('date')
                                if earnings_date:
                                    earnings_obj, created = Earnings.objects.get_or_create(
                                        stock=stock,
                                        earnings_date=earnings_date,
                                        defaults={
                                            'eps_estimate': earning_data.get('eps_estimate'),
                                            'eps_actual': earning_data.get('eps_actual'),
                                            'revenue_estimate': earning_data.get('revenue_estimate'),
                                            'revenue_actual': earning_data.get('revenue_actual'),
                                            'source': earning_data.get('source', 'api')
                                        }
                                    )
                                    
                                    if created:
                                        total_created += 1
                                    elif options['update_existing']:
                                        earnings_obj.eps_estimate = earning_data.get('eps_estimate') or earnings_obj.eps_estimate
                                        earnings_obj.eps_actual = earning_data.get('eps_actual') or earnings_obj.eps_actual
                                        earnings_obj.revenue_estimate = earning_data.get('revenue_estimate') or earnings_obj.revenue_estimate
                                        earnings_obj.revenue_actual = earning_data.get('revenue_actual') or earnings_obj.revenue_actual
                                        earnings_obj.save()
                                        total_updated += 1
                                    
                                    total_fetched += 1
                        
                    except Exception as e:
                        error_msg = f'Error fetching earnings for {stock.symbol}: {str(e)}'
                        errors.append(error_msg)
                        logger.error(error_msg)
                        continue
        
        # Summary
        self.stdout.write(self.style.SUCCESS('\n✅ Earnings fetch completed!'))
        self.stdout.write(f'  Total earnings fetched: {total_fetched}')
        self.stdout.write(self.style.SUCCESS(f'  New records created: {total_created}'))
        if total_updated > 0:
            self.stdout.write(self.style.SUCCESS(f'  Records updated: {total_updated}'))
        if errors:
            self.stdout.write(self.style.WARNING(f'  Errors: {len(errors)}'))
            if len(errors) <= 10:
                for error in errors:
                    self.stdout.write(self.style.WARNING(f'    - {error}'))
            else:
                self.stdout.write(self.style.WARNING(f'    (Showing first 10 errors)'))
                for error in errors[:10]:
                    self.stdout.write(self.style.WARNING(f'    - {error}'))

