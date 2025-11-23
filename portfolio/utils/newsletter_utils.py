# newsletter_utils.py
from django.utils import timezone
from datetime import timedelta
from portfolio.models import Stock, Dividend, StockPrice, ValuationMetric, NewsletterSubscription
import logging

logger = logging.getLogger(__name__)

class DividendNewsletterGenerator:
    def __init__(self):
        self.week_start = timezone.now().date()
        self.week_end = self.week_start + timedelta(days=7)
    
    def get_top_dividend_stocks(self, limit=10, min_yield=0.01, max_yield=0.20):
        """
        Get top dividend stocks for the upcoming week with various filters
        """
        try:
            # Get dividends in the upcoming week
            upcoming_dividends = Dividend.objects.filter(
                ex_dividend_date__gte=self.week_start,
                ex_dividend_date__lte=self.week_end,
                yield_percent__gte=min_yield,
                yield_percent__lte=max_yield
            ).select_related('stock').order_by('-yield_percent')[:limit]
            
            stocks_data = []
            for dividend in upcoming_dividends:
                # Get latest price
                latest_price = StockPrice.objects.filter(
                    stock=dividend.stock
                ).order_by('-price_date').first()
                
                # Get valuation metrics if available - FIXED: use 'valuations' instead of 'valuationmetric_set'
                valuation = dividend.stock.valuations.order_by('-metric_date').first()
                
                stock_data = {
                    'symbol': dividend.stock.symbol,
                    'company_name': dividend.stock.company_name,
                    'sector': dividend.stock.sector or '',
                    'dividend_amount': float(dividend.amount) if dividend.amount else 0,
                    'dividend_yield': float(dividend.yield_percent) if dividend.yield_percent else 0,
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
        
        # Calculate statistics - handle Decimal types
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
                'average_yield': round(avg_yield * 100, 2),
                'sectors_covered': sectors,
                'highest_yield': round(highest_yield * 100, 2),
                'lowest_yield': round(lowest_yield * 100, 2),
            }
        }
        
        return content