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
    Watchlist, DividendAlert, ValuationMetric, AnalystRating, Transaction
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
        """Calculate annual dividend income: (per-share amount) × shares × payments per year."""
        if not dividend_amount or not shares_owned:
            return 0
        if not frequency or frequency == 'Unknown':
            frequency = 'Quarterly'  # Default when unknown (most common)
        multiplier = PortfolioService.FREQUENCY_MULTIPLIER.get(frequency, 4)
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
        from .models import ValuationMetric
        latest_dividends = Dividend.objects.filter(stock=OuterRef('pk')).order_by('-ex_dividend_date')
        upcoming_dividends = Dividend.objects.filter(
            stock=OuterRef('pk'),
            ex_dividend_date__gte=timezone.now().date()
        ).order_by('ex_dividend_date')
        latest_prices = StockPrice.objects.filter(stock=OuterRef('pk')).order_by('-price_date')
        latest_valuations = ValuationMetric.objects.filter(stock=OuterRef('pk')).order_by('-metric_date')
        
        return Stock.objects.filter(show_in_listing=True).annotate(
            latest_dividend_amount=Subquery(latest_dividends.values('amount')[:1]),
            latest_dividend_yield=Subquery(latest_dividends.values('yield_percent')[:1]),
            latest_dividend_date=Subquery(latest_dividends.values('ex_dividend_date')[:1]),
            latest_dividend_frequency=Subquery(latest_dividends.values('frequency')[:1]),
            upcoming_dividend_date=Subquery(upcoming_dividends.values('ex_dividend_date')[:1]),
            latest_price_value=Subquery(latest_prices.values('last_price')[:1]),
            latest_price_date=Subquery(latest_prices.values('price_date')[:1]),
            market_cap_value=Subquery(latest_valuations.values('market_cap')[:1]),
            pe_ratio_value=Subquery(latest_valuations.values('pe_ratio')[:1]),
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


class TransactionService:
    """Service for transaction and cost basis calculation"""
    
    @staticmethod
    def calculate_cost_basis_fifo(user, stock, shares_to_sell):
        """Calculate cost basis using FIFO (First In First Out) method"""
        buy_transactions = Transaction.objects.filter(
            user=user,
            stock=stock,
            transaction_type='BUY',
            is_processed=False
        ).order_by('transaction_date', 'created_at')
        
        # Convert to Decimal for precise calculation
        remaining_shares = Decimal(str(shares_to_sell))
        total_cost_basis = Decimal('0.00')
        transactions_used = []
        
        for transaction in buy_transactions:
            if remaining_shares <= 0:
                break
            
            # Convert all to Decimal
            available_shares = Decimal(str(transaction.shares))
            shares_to_use = min(remaining_shares, available_shares)
            
            # Calculate cost per share: (price * shares + fees) / shares
            price_decimal = Decimal(str(transaction.price_per_share))
            fees_decimal = Decimal(str(transaction.fees))
            total_cost = (price_decimal * available_shares) + fees_decimal
            cost_per_share = total_cost / available_shares if available_shares > 0 else Decimal('0')
            
            # Cost basis for shares being sold
            cost_basis = shares_to_use * cost_per_share
            total_cost_basis += cost_basis
            
            transactions_used.append({
                'transaction': transaction,
                'shares_used': float(shares_to_use)
            })
            
            remaining_shares -= shares_to_use
        
        if remaining_shares > 0:
            # Not enough shares in buy transactions
            return None, None, f"Insufficient shares. Need {float(remaining_shares):.6f} more shares."
        
        return total_cost_basis, transactions_used, None
    
    @staticmethod
    def calculate_cost_basis_lifo(user, stock, shares_to_sell):
        """Calculate cost basis using LIFO (Last In First Out) method"""
        buy_transactions = Transaction.objects.filter(
            user=user,
            stock=stock,
            transaction_type='BUY',
            is_processed=False
        ).order_by('-transaction_date', '-created_at')
        
        # Convert to Decimal for precise calculation
        remaining_shares = Decimal(str(shares_to_sell))
        total_cost_basis = Decimal('0.00')
        transactions_used = []
        
        for transaction in buy_transactions:
            if remaining_shares <= 0:
                break
            
            # Convert all to Decimal
            available_shares = Decimal(str(transaction.shares))
            shares_to_use = min(remaining_shares, available_shares)
            
            # Calculate cost per share: (price * shares + fees) / shares
            price_decimal = Decimal(str(transaction.price_per_share))
            fees_decimal = Decimal(str(transaction.fees))
            total_cost = (price_decimal * available_shares) + fees_decimal
            cost_per_share = total_cost / available_shares if available_shares > 0 else Decimal('0')
            
            # Cost basis for shares being sold
            cost_basis = shares_to_use * cost_per_share
            total_cost_basis += cost_basis
            
            transactions_used.append({
                'transaction': transaction,
                'shares_used': float(shares_to_use)
            })
            
            remaining_shares -= shares_to_use
        
        if remaining_shares > 0:
            return None, None, f"Insufficient shares. Need {float(remaining_shares):.6f} more shares."
        
        return total_cost_basis, transactions_used, None
    
    @staticmethod
    def calculate_cost_basis_average(user, stock, shares_to_sell):
        """Calculate cost basis using Average Cost method"""
        buy_transactions = Transaction.objects.filter(
            user=user,
            stock=stock,
            transaction_type='BUY',
            is_processed=False
        )
        
        total_shares = Decimal('0.00')
        total_cost = Decimal('0.00')
        
        for transaction in buy_transactions:
            # Convert all to Decimal for precise calculation
            shares_decimal = Decimal(str(transaction.shares))
            price_decimal = Decimal(str(transaction.price_per_share))
            fees_decimal = Decimal(str(transaction.fees))
            
            total_shares += shares_decimal
            total_cost += (shares_decimal * price_decimal) + fees_decimal
        
        if total_shares == 0:
            return None, None, "No buy transactions found."
        
        average_cost_per_share = total_cost / total_shares
        shares_to_sell_decimal = Decimal(str(shares_to_sell))
        cost_basis = shares_to_sell_decimal * average_cost_per_share
        
        return cost_basis, [], None
    
    @staticmethod
    def calculate_cost_basis(user, stock, shares_to_sell, method='FIFO'):
        """Calculate cost basis using specified method"""
        if method == 'FIFO':
            return TransactionService.calculate_cost_basis_fifo(user, stock, shares_to_sell)
        elif method == 'LIFO':
            return TransactionService.calculate_cost_basis_lifo(user, stock, shares_to_sell)
        elif method == 'AVERAGE':
            return TransactionService.calculate_cost_basis_average(user, stock, shares_to_sell)
        else:
            return None, None, f"Unknown cost basis method: {method}"
    
    @staticmethod
    def get_unrealized_gains(user, stock):
        """Calculate unrealized gains for a stock"""
        try:
            portfolio_item = UserPortfolio.objects.get(user=user, stock=stock)
            if not portfolio_item.shares_owned or not portfolio_item.average_cost:
                return None
            
            # Get latest price
            latest_price = StockPrice.objects.filter(stock=stock).order_by('-price_date').first()
            if not latest_price:
                return None
            
            current_value = float(portfolio_item.shares_owned) * float(latest_price.last_price)
            cost_basis = float(portfolio_item.shares_owned) * float(portfolio_item.average_cost)
            unrealized_gain = current_value - cost_basis
            
            return {
                'unrealized_gain': unrealized_gain,
                'unrealized_gain_percent': (unrealized_gain / cost_basis * 100) if cost_basis > 0 else 0,
                'current_value': current_value,
                'cost_basis': cost_basis
            }
        except UserPortfolio.DoesNotExist:
            return None
    
    @staticmethod
    def get_realized_gains(user, stock=None, year=None):
        """Get realized gains from sell transactions"""
        transactions = Transaction.objects.filter(
            user=user,
            transaction_type='SELL',
            realized_gain_loss__isnull=False
        )
        
        if stock:
            transactions = transactions.filter(stock=stock)
        
        if year:
            transactions = transactions.filter(transaction_date__year=year)
        
        total_realized = sum(float(t.realized_gain_loss) for t in transactions if t.realized_gain_loss)
        
        return {
            'total_realized_gain': total_realized,
            'transactions': transactions,
            'count': transactions.count()
        }
    
    @staticmethod
    def update_portfolio_from_transactions(user, stock, recalculate_all=False):
        """
        Update UserPortfolio based on transactions
        
        Args:
            user: User object
            stock: Stock object
            recalculate_all: If True, recalculate from all transactions (used after deletion).
                           If False, only use unprocessed transactions (default for new transactions).
        """
        if recalculate_all:
            # After deletion, recalculate from ALL remaining transactions
            buy_transactions = Transaction.objects.filter(
                user=user,
                stock=stock,
                transaction_type='BUY'
            )
            
            sell_transactions = Transaction.objects.filter(
                user=user,
                stock=stock,
                transaction_type='SELL'
            )
        else:
            # For new transactions, only use unprocessed ones
            buy_transactions = Transaction.objects.filter(
                user=user,
                stock=stock,
                transaction_type='BUY',
                is_processed=False
            )
            
            sell_transactions = Transaction.objects.filter(
                user=user,
                stock=stock,
                transaction_type='SELL',
                is_processed=False
            )
        
        total_shares = Decimal('0.00')
        total_cost = Decimal('0.00')
        
        # Calculate from buy transactions
        for transaction in buy_transactions:
            total_shares += transaction.shares
            total_cost += (transaction.shares * transaction.price_per_share) + transaction.fees
        
        # Subtract sell transactions
        for transaction in sell_transactions:
            total_shares -= transaction.shares
        
        # Update or create portfolio item
        if total_shares > 0:
            average_cost = total_cost / total_shares if total_shares > 0 else Decimal('0.00')
            UserPortfolio.objects.update_or_create(
                user=user,
                stock=stock,
                defaults={
                    'shares_owned': int(total_shares),
                    'average_cost': average_cost
                }
            )
        else:
            # Remove from portfolio if no shares left
            UserPortfolio.objects.filter(user=user, stock=stock).delete()


