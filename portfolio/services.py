"""
Service layer for business logic separation
This module contains business logic that was previously in views
"""
from django.db.models import Subquery, OuterRef, Exists, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import (
    Stock, StockPrice, Dividend, UserPortfolio, 
    Watchlist, DividendAlert, ValuationMetric, AnalystRating
)
# PortfolioSnapshot imported conditionally to handle migration timing


class PortfolioService:
    """Service for portfolio-related business logic"""
    
    FREQUENCY_MULTIPLIER = {
        'Monthly': 12,
        'Quarterly': 4,
        'Semi-Annual': 2,
        'Annual': 1,
    }
    
    @staticmethod
    def calculate_annual_dividend(dividend_amount, shares_owned, frequency):
        """Calculate annual dividend income"""
        if not dividend_amount or not shares_owned or not frequency:
            return 0
        multiplier = PortfolioService.FREQUENCY_MULTIPLIER.get(frequency, 0)
        return float(dividend_amount * shares_owned * multiplier)
    
    @staticmethod
    def calculate_dividend_projection(portfolio_items, months=12):
        """Calculate projected dividend income for next N months"""
        from collections import defaultdict
        from datetime import timedelta
        
        today = timezone.now().date()
        projection = defaultdict(float)  # month -> total income
        
        for item in portfolio_items:
            if not item.latest_dividend_amount or not item.shares_owned or not item.latest_dividend_frequency:
                continue
            
            dividend_per_payment = float(item.latest_dividend_amount * item.shares_owned)
            frequency = item.latest_dividend_frequency
            
            # Get next payment date
            next_payment_date = item.latest_dividend_date
            if not next_payment_date:
                continue
            
            # Calculate payments for next N months
            months_to_project = months
            current_date = next_payment_date
            
            if frequency == 'Monthly':
                payments_per_month = 1
                days_between = 30
            elif frequency == 'Quarterly':
                payments_per_month = 1/3
                days_between = 90
            elif frequency == 'Semi-Annual':
                payments_per_month = 1/6
                days_between = 180
            elif frequency == 'Annual':
                payments_per_month = 1/12
                days_between = 365
            else:
                continue
            
            # Project payments
            payment_count = 0
            while payment_count < months * payments_per_month and current_date <= today + timedelta(days=months*30):
                month_key = current_date.strftime('%Y-%m')
                projection[month_key] += dividend_per_payment
                current_date += timedelta(days=days_between)
                payment_count += 1
        
        # Convert to sorted list
        projection_list = []
        for i in range(months):
            month_date = today + timedelta(days=i*30)
            month_key = month_date.strftime('%Y-%m')
            month_name = month_date.strftime('%b %Y')
            projection_list.append({
                'month': month_name,
                'month_key': month_key,
                'income': round(projection.get(month_key, 0), 2),
                'cumulative': 0  # Will calculate below
            })
        
        # Calculate cumulative
        cumulative = 0
        for item in projection_list:
            cumulative += item['income']
            item['cumulative'] = round(cumulative, 2)
        
        return projection_list
    
    @staticmethod
    def create_portfolio_snapshot(user):
        """Create a snapshot of current portfolio state"""
        try:
            from .models import PortfolioSnapshot
            from django.db import connection
            
            # Check if table exists
            with connection.cursor() as cursor:
                if connection.vendor == 'postgresql':
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = 'portfolio_portfoliosnapshot'
                        );
                    """)
                    table_exists = cursor.fetchone()[0]
                else:
                    # For SQLite
                    cursor.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='table' AND name='portfolio_portfoliosnapshot';
                    """)
                    table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                return None
            
            portfolio_items = PortfolioService.get_portfolio_with_annotations(user)
            
            total_value = 0
            total_investment = 0
            annual_dividend_income = 0
            total_holdings = portfolio_items.count()
            
            for item in portfolio_items:
                if item.latest_price_value and item.shares_owned:
                    total_value += float(item.shares_owned * item.latest_price_value)
                if item.average_cost and item.shares_owned:
                    total_investment += float(item.shares_owned * item.average_cost)
                
                annual_dividend_income += PortfolioService.calculate_annual_dividend(
                    item.latest_dividend_amount,
                    item.shares_owned,
                    item.latest_dividend_frequency
                )
            
            total_gain_loss = total_value - total_investment
            total_roi_percent = (total_gain_loss / total_investment * 100) if total_investment > 0 else 0
            dividend_yield = (annual_dividend_income / total_value * 100) if total_value > 0 else 0
            
            snapshot, created = PortfolioSnapshot.objects.update_or_create(
                user=user,
                snapshot_date=timezone.now().date(),
                defaults={
                    'total_value': total_value,
                    'total_investment': total_investment,
                    'total_gain_loss': total_gain_loss,
                    'total_roi_percent': total_roi_percent,
                    'annual_dividend_income': annual_dividend_income,
                    'dividend_yield': dividend_yield,
                    'total_holdings': total_holdings,
                }
            )
            
            return snapshot
        except Exception as e:
            # Model doesn't exist yet or table doesn't exist - return None
            # Log at debug level to avoid noise
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Could not create portfolio snapshot: {e}")
            return None
    
    @staticmethod
    def get_portfolio_performance_history(user, days=180):
        """Get portfolio performance history for last N days"""
        try:
            from .models import PortfolioSnapshot
            from django.db import connection
            
            # Check if table exists first
            with connection.cursor() as cursor:
                if connection.vendor == 'postgresql':
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = 'portfolio_portfoliosnapshot'
                        );
                    """)
                    table_exists = cursor.fetchone()[0]
                else:
                    # For SQLite
                    cursor.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='table' AND name='portfolio_portfoliosnapshot';
                    """)
                    table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                return None
            
            cutoff_date = timezone.now().date() - timedelta(days=days)
            snapshots = PortfolioSnapshot.objects.filter(
                user=user,
                snapshot_date__gte=cutoff_date
            ).order_by('snapshot_date')
            
            return snapshots
        except Exception:
            # Model doesn't exist yet or table doesn't exist - return None
            # This will be handled gracefully in the view
            return None
    
    @staticmethod
    def get_portfolio_with_annotations(user):
        """Get portfolio items with optimized annotations"""
        return UserPortfolio.objects.filter(user=user).select_related('stock').annotate(
            latest_price_value=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('last_price')[:1]
            ),
            latest_price_date=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('price_date')[:1]
            ),
            latest_dividend_amount=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('amount')[:1]
            ),
            latest_dividend_yield=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('yield_percent')[:1]
            ),
            latest_dividend_frequency=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('frequency')[:1]
            ),
            latest_dividend_date=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('ex_dividend_date')[:1]
            ),
        )
    
    @staticmethod
    def get_watchlist_with_annotations(user):
        """Get watchlist items with optimized annotations"""
        return Watchlist.objects.filter(user=user).select_related('stock').annotate(
            latest_price_value=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('last_price')[:1]
            ),
            latest_price_date=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('price_date')[:1]
            ),
            latest_dividend_amount=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('amount')[:1]
            ),
            latest_dividend_yield=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('yield_percent')[:1]
            ),
            latest_dividend_date=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('ex_dividend_date')[:1]
            ),
            latest_dividend_frequency=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('frequency')[:1]
            ),
        )


class StockService:
    """Service for stock-related business logic"""
    
    @staticmethod
    def get_stocks_with_annotations():
        """Get stocks with all required annotations for listing"""
        latest_dividends = Dividend.objects.filter(stock=OuterRef('pk')).order_by('-ex_dividend_date')
        upcoming_dividends = Dividend.objects.filter(
            stock=OuterRef('pk'),
            ex_dividend_date__gte=timezone.now().date()
        ).order_by('ex_dividend_date')
        latest_prices = StockPrice.objects.filter(stock=OuterRef('pk')).order_by('-price_date')
        
        return Stock.objects.all().annotate(
            latest_dividend_amount=Subquery(latest_dividends.values('amount')[:1]),
            latest_dividend_yield=Subquery(latest_dividends.values('yield_percent')[:1]),
            latest_dividend_date=Subquery(latest_dividends.values('ex_dividend_date')[:1]),
            latest_dividend_frequency=Subquery(latest_dividends.values('frequency')[:1]),
            upcoming_dividend_date=Subquery(upcoming_dividends.values('ex_dividend_date')[:1]),
            latest_price_value=Subquery(latest_prices.values('last_price')[:1]),
            latest_price_date=Subquery(latest_prices.values('price_date')[:1]),
            has_dividend=Exists(Dividend.objects.filter(stock=OuterRef('pk')))
        )
    
    @staticmethod
    def get_upcoming_dividends(days=30, limit=12):
        """Get upcoming dividends for the next N days"""
        today = timezone.now().date()
        end_date = today + timedelta(days=days)
        
        return Dividend.objects.filter(
            ex_dividend_date__gte=today,
            ex_dividend_date__lte=end_date
        ).select_related('stock').annotate(
            latest_price=Subquery(
                StockPrice.objects.filter(
                    stock=OuterRef('stock_id')
                ).order_by('-price_date').values('last_price')[:1]
            ),
            latest_price_date=Subquery(
                StockPrice.objects.filter(
                    stock=OuterRef('stock_id')
                ).order_by('-price_date').values('price_date')[:1]
            )
        ).order_by('ex_dividend_date')[:limit]


class AlertService:
    """Service for alert-related business logic"""
    
    MAX_DIVIDEND_ALERTS = 5
    MAX_WATCHLIST_ITEMS = 10
    
    @staticmethod
    def can_add_dividend_alert(user):
        """Check if user can add another dividend alert"""
        current_count = DividendAlert.objects.filter(user=user).count()
        return current_count < AlertService.MAX_DIVIDEND_ALERTS
    
    @staticmethod
    def can_add_watchlist_item(user):
        """Check if user can add another watchlist item"""
        current_count = Watchlist.objects.filter(user=user).count()
        return current_count < AlertService.MAX_WATCHLIST_ITEMS
    
    @staticmethod
    def get_alerts_with_annotations(user):
        """Get dividend alerts with optimized annotations"""
        return DividendAlert.objects.filter(user=user).select_related('stock').annotate(
            latest_dividend_amount=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('amount')[:1]
            ),
            latest_dividend_yield=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('yield_percent')[:1]
            ),
            latest_dividend_date=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('ex_dividend_date')[:1]
            ),
            latest_dividend_frequency=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('frequency')[:1]
            ),
        )


