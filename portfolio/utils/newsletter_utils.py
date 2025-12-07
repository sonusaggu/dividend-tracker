# newsletter_utils.py
from django.utils import timezone
from datetime import timedelta
from portfolio.models import Stock, Dividend, StockPrice, ValuationMetric, NewsletterSubscription
import logging

logger = logging.getLogger(__name__)

class DividendNewsletterGenerator:
    def __init__(self):
        self.week_start = timezone.now().date()
        self.week_end = self.week_start + timedelta(days=30)  # Extended to 30 days to ensure we have stocks
    
    def get_top_dividend_stocks(self, limit=10, min_yield=0.01, max_yield=0.20):
        """
        Get top dividend stocks for the upcoming period with various filters
        Note: yield_percent is stored as percentage (0-100), not decimal (0-1)
        """
        try:
            # Get all upcoming dividends first
            base_query = Dividend.objects.filter(
                ex_dividend_date__gte=self.week_start,
                ex_dividend_date__lte=self.week_end,
                ex_dividend_date__isnull=False
            ).select_related('stock')
            
            # Yields are stored as percentages (0-100), convert filters from decimal to percentage
            min_yield_pct = min_yield * 100
            max_yield_pct = max_yield * 100
            
            # Filter by yield (as percentage)
            upcoming_dividends = base_query.filter(
                yield_percent__gte=min_yield_pct,
                yield_percent__lte=max_yield_pct
            )
            
            # If no results with yield filter, try without yield filter (but still require yield_percent exists)
            if not upcoming_dividends.exists():
                logger.info(f"No dividends found with yield filters ({min_yield_pct}%-{max_yield_pct}%), trying without yield filters")
                upcoming_dividends = base_query.filter(
                    yield_percent__isnull=False
                )
            
            # If still no results, get any upcoming dividends (even without yield)
            if not upcoming_dividends.exists():
                logger.info("No dividends found with yield, trying any upcoming dividends")
                upcoming_dividends = base_query
            
            # Log for debugging before limiting
            count_before = upcoming_dividends.count()
            logger.info(f"Newsletter: Found {count_before} upcoming dividends for period {self.week_start} to {self.week_end}")
            
            # Order and limit
            upcoming_dividends = upcoming_dividends.order_by('-yield_percent', 'ex_dividend_date')[:limit]
            
            stocks_data = []
            for dividend in upcoming_dividends:
                # Get latest price
                latest_price = StockPrice.objects.filter(
                    stock=dividend.stock
                ).order_by('-price_date').first()
                
                # Get valuation metrics if available - FIXED: use 'valuations' instead of 'valuationmetric_set'
                valuation = dividend.stock.valuations.order_by('-metric_date').first()
                
                # Keep yield as percentage (0-100) since templates expect percentage format
                yield_value = float(dividend.yield_percent) if dividend.yield_percent else 0
                
                stock_data = {
                    'symbol': dividend.stock.symbol,
                    'company_name': dividend.stock.company_name,
                    'sector': dividend.stock.sector or '',
                    'dividend_amount': float(dividend.amount) if dividend.amount else 0,
                    'dividend_yield': yield_value,  # Stored as percentage (0-100) to match template expectations
                    'ex_dividend_date': dividend.ex_dividend_date,
                    'frequency': dividend.frequency,
                    'current_price': float(latest_price.last_price) if latest_price and latest_price.last_price else None,
                    'pe_ratio': float(valuation.pe_ratio) if valuation and valuation.pe_ratio else None,
                    'market_cap': valuation.market_cap if valuation else None,
                    'days_until': (dividend.ex_dividend_date - self.week_start).days if dividend.ex_dividend_date else None
                }
                stocks_data.append(stock_data)
            
            return stocks_data
            
        except Exception as e:
            logger.error(f"Error getting top dividend stocks: {e}")
            return []
    
    def get_stocks_by_strategy(self, strategy='high_yield', limit=10):
        """
        Get stocks based on different investment strategies
        """
        strategies = {
            'high_yield': {'min_yield': 0.05, 'max_yield': 0.20},
            'moderate_yield': {'min_yield': 0.03, 'max_yield': 0.08},
            'growth_income': {'min_yield': 0.02, 'max_yield': 0.05},
            'blue_chip': {'min_yield': 0.01, 'max_yield': 0.06},
        }
        
        # Map strategy names if needed
        strategy_mapping = {
            'growth_income': 'growth_income',
            'high_yield': 'high_yield',
            'blue_chip': 'blue_chip',
        }
        
        strategy = strategy_mapping.get(strategy, 'high_yield')
        
        if strategy not in strategies:
            strategy = 'high_yield'
        
        params = strategies[strategy]
        return self.get_top_dividend_stocks(limit=limit, **params)
    
    def generate_newsletter_content(self, user=None):
        """
        Generate complete newsletter content
        """
        # Get user preferences if available
        preferences = {}
        if user and hasattr(user, 'newsletter_subscription'):
            subscription = user.newsletter_subscription
            if subscription and subscription.preferences:
                preferences = subscription.preferences
        
        strategy = preferences.get('strategy', 'high_yield') if preferences else 'high_yield'
        limit = preferences.get('stocks_count', 10) if preferences else 10
        
        # Ensure limit is valid
        if limit not in [5, 10, 15]:
            limit = 10
        
        # Get stocks based on strategy
        top_stocks = self.get_stocks_by_strategy(strategy, limit)
        
        # Log for debugging
        logger.info(f"Newsletter: Generated {len(top_stocks)} stocks for strategy '{strategy}' with limit {limit}")
        
        # Calculate statistics - yields are already in percentage format (0-100)
        if top_stocks:
            yields = [float(stock['dividend_yield']) if stock['dividend_yield'] else 0 for stock in top_stocks]
            avg_yield = sum(yields) / len(yields) if yields else 0
            sectors = list(set(stock['sector'] for stock in top_stocks if stock.get('sector')))
            highest_yield = max(yields) if yields else 0
            lowest_yield = min(yields) if yields else 0
        else:
            avg_yield = 0
            sectors = []
            highest_yield = 0
            lowest_yield = 0
        
        content = {
            'generated_date': timezone.now(),
            'week_start': self.week_start,
            'week_end': self.week_end,
            'strategy_used': strategy,
            'top_stocks': top_stocks,
            'statistics': {
                'total_stocks': len(top_stocks),
                'average_yield': round(avg_yield, 2),  # Already in percentage format, no need to multiply
                'sectors_covered': sectors,
                'highest_yield': round(highest_yield, 2),  # Already in percentage format
                'lowest_yield': round(lowest_yield, 2),  # Already in percentage format
            }
        }
        
        return content