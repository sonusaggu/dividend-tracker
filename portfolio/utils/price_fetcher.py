"""
Stock price fetching utility
Fetches stock prices from external APIs when not available in database
Converts all prices to CAD for consistency
"""
import requests
import logging
import time
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from decouple import config

logger = logging.getLogger(__name__)


class PriceFetcher:
    """Fetches stock prices from external APIs and converts to CAD"""
    
    def __init__(self):
        # Try to get API key from settings, fallback to environment variable
        self.alpha_vantage_key = config('ALPHA_VANTAGE_KEY', default='')
        # Rate limiting: track last API call time
        self.last_alphavantage_call = 0
        self.min_delay_between_calls = 12.0  # Alpha Vantage free tier: 5 calls per minute = 12 seconds between calls
        # Cache exchange rate for 1 hour
        self.usd_to_cad_rate = None
        self.exchange_rate_cache_time = 0
        self.exchange_rate_cache_duration = 3600  # 1 hour
    
    def get_usd_to_cad_rate(self):
        """
        Get USD to CAD exchange rate
        Uses a free API or fallback rate
        Returns: Decimal exchange rate
        """
        current_time = time.time()
        
        # Return cached rate if still valid
        if self.usd_to_cad_rate and (current_time - self.exchange_rate_cache_time) < self.exchange_rate_cache_duration:
            return self.usd_to_cad_rate
        
        try:
            # Try to get exchange rate from exchangerate-api.com (free tier)
            url = 'https://api.exchangerate-api.com/v4/latest/USD'
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if 'rates' in data and 'CAD' in data['rates']:
                rate = Decimal(str(data['rates']['CAD']))
                self.usd_to_cad_rate = rate
                self.exchange_rate_cache_time = current_time
                logger.info(f"Fetched USD to CAD rate: {rate}")
                return rate
        except Exception as e:
            logger.warning(f"Could not fetch exchange rate from API: {e}, using fallback rate")
        
        # Fallback to approximate rate (1 USD = 1.35 CAD)
        fallback_rate = Decimal('1.35')
        logger.info(f"Using fallback USD to CAD rate: {fallback_rate}")
        return fallback_rate
    
    def convert_to_cad(self, price, from_currency):
        """
        Convert price to CAD
        Args:
            price: Decimal price value
            from_currency: Source currency code (e.g., 'USD', 'CAD')
        Returns: (converted_price, 'CAD') tuple
        """
        if from_currency.upper() == 'CAD':
            return price, 'CAD'
        
        if from_currency.upper() == 'USD':
            rate = self.get_usd_to_cad_rate()
            cad_price = price * rate
            return cad_price, 'CAD'
        
        # For other currencies, log warning and return as-is (could add more conversions)
        logger.warning(f"Currency conversion not supported for {from_currency}, returning price as-is")
        return price, 'CAD'  # Default to CAD
    
    def fetch_price_from_alphavantage(self, symbol):
        """
        Fetch current stock price from Alpha Vantage API
        Returns: (price, currency) tuple or (None, None) if failed
        """
        if not self.alpha_vantage_key:
            logger.debug(f"Alpha Vantage API key not configured")
            return None, None
        
        # Check rate limiting
        current_time = time.time()
        time_since_last_call = current_time - self.last_alphavantage_call
        if time_since_last_call < self.min_delay_between_calls:
            wait_time = self.min_delay_between_calls - time_since_last_call
            logger.debug(f"Rate limiting: waiting {wait_time:.1f} seconds before Alpha Vantage call")
            time.sleep(wait_time)
        
        try:
            # Alpha Vantage Global Quote endpoint
            url = 'https://www.alphavantage.co/query'
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': symbol,
                'apikey': self.alpha_vantage_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            self.last_alphavantage_call = time.time()
            
            # Check for API errors
            if 'Error Message' in data:
                logger.warning(f"Alpha Vantage error for {symbol}: {data['Error Message']}")
                return None, None
            
            if 'Note' in data:
                logger.warning(f"Alpha Vantage rate limit for {symbol}: {data['Note']}")
                return None, None
            
            # Parse response
            if 'Global Quote' in data and data['Global Quote']:
                quote = data['Global Quote']
                price_str = quote.get('05. price', '0')
                currency = quote.get('08. currency', 'USD')
                
                try:
                    price = Decimal(str(price_str))
                    if price > 0:
                        return price, currency
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not parse price for {symbol}: {price_str}, error: {e}")
            
            return None, None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching price from Alpha Vantage for {symbol}: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error fetching price for {symbol}: {e}", exc_info=True)
            return None, None
    
    def fetch_price(self, symbol):
        """
        Fetch stock price from available APIs and convert to CAD
        Returns: (price_in_cad, 'CAD') tuple or (None, None) if failed
        """
        # Try Alpha Vantage first
        price, currency = self.fetch_price_from_alphavantage(symbol)
        
        if price:
            # Convert to CAD
            cad_price, cad_currency = self.convert_to_cad(price, currency)
            return cad_price, cad_currency
        
        # Could add more API sources here (Yahoo Finance, etc.)
        # For now, return None if Alpha Vantage fails
        return None, None


def get_or_fetch_stock_price(stock):
    """
    Get stock price from database, or fetch from API if not available
    Returns: StockPrice object or None
    """
    from portfolio.models import StockPrice
    
    # Check if we have a recent price (within last 7 days)
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    latest_price = StockPrice.objects.filter(
        stock=stock,
        price_date__gte=week_ago
    ).order_by('-price_date').first()
    
    if latest_price:
        return latest_price
    
    # No recent price, try to fetch from API
    logger.info(f"No recent price found for {stock.symbol}, attempting to fetch from API")
    fetcher = PriceFetcher()
    price, currency = fetcher.fetch_price(stock.symbol)
    
    if price:
        # Price should already be in CAD from fetch_price, but ensure it is
        if currency != 'CAD':
            price, currency = fetcher.convert_to_cad(price, currency)
        
        # Save the fetched price (always in CAD)
        try:
            stock_price = StockPrice.objects.create(
                stock=stock,
                price_date=today,
                last_price=price,
                currency='CAD',  # Always store as CAD
            )
            logger.info(f"Successfully fetched and saved price for {stock.symbol}: ${price} CAD")
            return stock_price
        except Exception as e:
            logger.error(f"Error saving fetched price for {stock.symbol}: {e}", exc_info=True)
            return None
    
    logger.warning(f"Could not fetch price for {stock.symbol} from API")
    return None

