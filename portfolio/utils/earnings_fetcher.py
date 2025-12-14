"""
Earnings data fetching utility
Fetches earnings calendar and earnings data from free APIs
Supports multiple API sources as fallbacks
"""
import requests
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from decouple import config

logger = logging.getLogger(__name__)


class EarningsFetcher:
    """Fetches earnings data from multiple free API sources"""
    
    def __init__(self):
        # API Keys (optional - some APIs work without keys)
        self.alpha_vantage_key = config('ALPHA_VANTAGE_KEY', default='')
        self.finnhub_key = config('FINNHUB_API_KEY', default='')
        self.polygon_key = config('POLYGON_API_KEY', default='')
        
        # Rate limiting
        self.last_api_call = {}
        self.min_delay = {
            'alphavantage': 12.0,  # 5 calls/min
            'finnhub': 1.0,  # 60 calls/min
            'polygon': 1.0,  # 5 calls/min
        }
    
    def _wait_for_rate_limit(self, api_name):
        """Wait if needed to respect rate limits"""
        if api_name not in self.last_api_call:
            self.last_api_call[api_name] = 0
        
        elapsed = time.time() - self.last_api_call[api_name]
        min_delay = self.min_delay.get(api_name, 1.0)
        
        if elapsed < min_delay:
            wait_time = min_delay - elapsed
            time.sleep(wait_time)
        
        self.last_api_call[api_name] = time.time()
    
    def _is_canadian_stock(self, symbol):
        """
        Check if a stock is Canadian (TSX)
        Canadian stocks typically have .TO or .V suffix, or are TSX stocks
        """
        if not symbol:
            return False
        
        symbol_upper = symbol.upper()
        # Check for TSX suffixes
        if symbol_upper.endswith('.TO') or symbol_upper.endswith('.V'):
            return True
        
        # Check if it's a TSX stock in database
        try:
            from portfolio.models import Stock
            stock = Stock.objects.filter(symbol=symbol_upper).first()
            if stock:
                # Check if it's TSX60 member or has TSX-related code
                if stock.tsx60_member or (stock.code and ('TSX' in stock.code.upper() or '.TO' in stock.code.upper())):
                    return True
        except Exception:
            pass
        
        return False
    
    def fetch_earnings_calendar(self, start_date=None, end_date=None, symbol=None, canadian_only=True):
        """
        Fetch earnings calendar from available APIs
        ONLY fetches Canadian stocks by default
        Uses Finnhub for Canadian stocks
        Returns list of earnings events (Canadian stocks only)
        """
        if not start_date:
            start_date = timezone.now().date()
        if not end_date:
            end_date = start_date + timedelta(days=30)
        
        # Check if this is a Canadian stock
        is_canadian = self._is_canadian_stock(symbol) if symbol else True  # Default to True for calendar
        
        # If symbol is provided and it's not Canadian, return empty
        if symbol and not is_canadian and canadian_only:
            logger.info(f"Skipping non-Canadian stock {symbol}")
            return []
        
        # Try multiple APIs in order of preference
        earnings_data = []
        
        # 1. Try Finnhub ONLY for Canadian stocks (best for TSX)
        if self.finnhub_key:
            try:
                data = self._fetch_from_finnhub(start_date, end_date, symbol)
                if data:
                    # Filter to only Canadian stocks
                    if canadian_only:
                        filtered_data = []
                        for event in data:
                            event_symbol = event.get('symbol', '')
                            if self._is_canadian_stock(event_symbol):
                                filtered_data.append(event)
                        earnings_data.extend(filtered_data)
                        logger.info(f"Fetched {len(filtered_data)} Canadian earnings from Finnhub")
                    else:
                        earnings_data.extend(data)
                        logger.info(f"Fetched {len(data)} earnings from Finnhub")
            except Exception as e:
                logger.warning(f"Finnhub earnings fetch failed: {e}")
        
        # 2. Fallback: Financial Modeling Prep (filter for Canadian stocks)
        if not earnings_data:
            try:
                data = self._fetch_from_fmp(start_date, end_date, symbol)
                if data:
                    # Filter to only Canadian stocks
                    if canadian_only:
                        filtered_data = []
                        for event in data:
                            event_symbol = event.get('symbol', '')
                            if self._is_canadian_stock(event_symbol):
                                filtered_data.append(event)
                        earnings_data.extend(filtered_data)
                        logger.info(f"Fetched {len(filtered_data)} Canadian earnings from FMP")
                    else:
                        earnings_data.extend(data)
                        logger.info(f"Fetched {len(data)} earnings from FMP")
            except Exception as e:
                logger.warning(f"FMP earnings fetch failed: {e}")
        
        return earnings_data
    
    def _fetch_from_finnhub(self, start_date, end_date, symbol=None):
        """Fetch earnings calendar from Finnhub API"""
        self._wait_for_rate_limit('finnhub')
        
        url = "https://finnhub.io/api/v1/calendar/earnings"
        params = {
            'from': start_date.strftime('%Y-%m-%d'),
            'to': end_date.strftime('%Y-%m-%d'),
            'token': self.finnhub_key
        }
        
        if symbol:
            params['symbol'] = symbol.upper()
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            earnings = []
            if 'earningsCalendar' in data:
                for event in data['earningsCalendar']:
                    earnings.append({
                        'symbol': event.get('symbol', ''),
                        'company_name': event.get('name', ''),
                        'date': datetime.strptime(event.get('date', ''), '%Y-%m-%d').date() if event.get('date') else None,
                        'eps_estimate': event.get('epsEstimate'),
                        'eps_actual': event.get('epsActual'),
                        'revenue_estimate': event.get('revenueEstimate'),
                        'revenue_actual': event.get('revenueActual'),
                        'time': event.get('time', ''),  # 'bmo' (before market open) or 'amc' (after market close)
                        'source': 'finnhub'
                    })
            
            return earnings
        except Exception as e:
            logger.error(f"Error fetching from Finnhub: {e}")
            return None
    
    def _fetch_from_alphavantage(self, symbol=None):
        """Fetch earnings from Alpha Vantage (limited - only for specific symbol)"""
        if not symbol:
            return None  # Alpha Vantage requires symbol
        
        self._wait_for_rate_limit('alphavantage')
        
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'EARNINGS',
            'symbol': symbol.upper(),
            'apikey': self.alpha_vantage_key
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'Error Message' in data or 'Note' in data:
                return None
            
            earnings = []
            if 'quarterlyEarnings' in data:
                for event in data['quarterlyEarnings'][:4]:  # Last 4 quarters
                    earnings.append({
                        'symbol': symbol.upper(),
                        'date': datetime.strptime(event.get('fiscalDateEnding', ''), '%Y-%m-%d').date() if event.get('fiscalDateEnding') else None,
                        'eps_actual': float(event.get('reportedEPS', 0)) if event.get('reportedEPS') else None,
                        'source': 'alphavantage'
                    })
            
            return earnings
        except Exception as e:
            logger.error(f"Error fetching from Alpha Vantage: {e}")
            return None
    
    def _fetch_from_polygon(self, start_date, end_date, symbol=None):
        """Fetch earnings from Polygon.io"""
        self._wait_for_rate_limit('polygon')
        
        url = "https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{date}"
        
        # Polygon requires date-by-date fetching, so we'll use their earnings endpoint
        earnings_url = "https://api.polygon.io/v3/reference/options/contracts"
        
        # Actually, let's use their simpler approach - get earnings for a symbol
        if symbol:
            url = f"https://api.polygon.io/v2/reference/news"
            params = {
                'ticker': symbol.upper(),
                'limit': 100,
                'apiKey': self.polygon_key
            }
            # This is for news, not earnings. Polygon's earnings endpoint requires paid tier.
            return None
        
        return None
    
    def _fetch_from_fmp(self, start_date, end_date, symbol=None):
        """Fetch earnings from Financial Modeling Prep (free demo key)"""
        # FMP demo key: 'demo' (limited but works)
        api_key = config('FMP_API_KEY', default='demo')
        
        if symbol:
            # Get earnings for specific symbol
            url = f"https://financialmodelingprep.com/api/v3/historical/earning_calendar/{symbol.upper()}"
        else:
            # Get earnings calendar
            url = "https://financialmodelingprep.com/api/v3/earning_calendar"
        
        params = {
            'apikey': api_key,
            'from': start_date.strftime('%Y-%m-%d'),
            'to': end_date.strftime('%Y-%m-%d')
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            earnings = []
            if isinstance(data, list):
                for event in data:
                    earnings.append({
                        'symbol': event.get('symbol', ''),
                        'company_name': event.get('name', ''),
                        'date': datetime.strptime(event.get('date', ''), '%Y-%m-%d').date() if event.get('date') else None,
                        'eps_estimate': event.get('epsEstimated'),
                        'eps_actual': event.get('eps'),
                        'revenue_estimate': event.get('revenueEstimated'),
                        'revenue_actual': event.get('revenue'),
                        'time': event.get('time', ''),
                        'source': 'fmp'
                    })
            
            return earnings
        except Exception as e:
            logger.error(f"Error fetching from FMP: {e}")
            return None
    
    def fetch_stock_earnings(self, symbol):
        """Fetch earnings history for a specific stock"""
        # Check if Canadian stock
        is_canadian = self._is_canadian_stock(symbol)
        
        # For Canadian stocks, try Finnhub first
        if is_canadian and self.finnhub_key:
            try:
                # Finnhub doesn't have historical earnings endpoint in free tier
                # But we can try to get recent earnings from calendar
                today = timezone.now().date()
                start_date = today - timedelta(days=365)  # Last year
                end_date = today
                data = self._fetch_from_finnhub(start_date, end_date, symbol)
                if data:
                    # Convert to earnings history format
                    earnings = []
                    for event in data[:8]:  # Last 8 quarters
                        earnings.append({
                            'symbol': symbol.upper(),
                            'date': event.get('date'),
                            'eps_actual': event.get('eps_actual'),
                            'eps_estimate': event.get('eps_estimate'),
                            'revenue_actual': event.get('revenue_actual'),
                            'revenue_estimate': event.get('revenue_estimate'),
                            'source': 'finnhub'
                        })
                    if earnings:
                        return earnings
            except Exception as e:
                logger.warning(f"Finnhub earnings history failed: {e}")
        
        # For non-Canadian stocks, try Alpha Vantage first (has historical earnings)
        if not is_canadian and self.alpha_vantage_key:
            try:
                return self._fetch_from_alphavantage(symbol)
            except Exception as e:
                logger.warning(f"Alpha Vantage earnings history failed: {e}")
        
        # Fallback to FMP (works for all stocks)
        try:
            url = f"https://financialmodelingprep.com/api/v3/historical/earning_calendar/{symbol.upper()}"
            params = {'apikey': config('FMP_API_KEY', default='demo')}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            earnings = []
            if isinstance(data, list):
                for event in data[:8]:  # Last 8 quarters
                    earnings.append({
                        'symbol': symbol.upper(),
                        'date': datetime.strptime(event.get('date', ''), '%Y-%m-%d').date() if event.get('date') else None,
                        'eps_actual': event.get('eps'),
                        'eps_estimate': event.get('epsEstimated'),
                        'revenue_actual': event.get('revenue'),
                        'revenue_estimate': event.get('revenueEstimated'),
                        'source': 'fmp'
                    })
            
            return earnings
        except Exception as e:
            logger.error(f"Error fetching stock earnings: {e}")
            return None

