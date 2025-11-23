import requests
import logging
from datetime import datetime, date
from decimal import Decimal
from django.db import transaction, connection
from django.utils import timezone
from django.db.models import Q
from portfolio.models import Stock, StockPrice, Dividend, ValuationMetric, AnalystRating

logger = logging.getLogger(__name__)

class TSXScraper:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://tsx.exdividend.ca"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest"
        }
        self.session.headers.update(self.headers)

    def _get_csrf_token(self):
        """Get CSRF token from the API"""
        try:
            response = self.session.post(
                f"{self.base_url}/t/",
                data={"n": '[{"key":"userAgent","value":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}]'},
                timeout=10
            )
            if response.status_code == 200:
                return response.json().get("data")
        except Exception as e:
            logger.error(f"Error getting CSRF token: {str(e)}")
        return None

    def scrape_stocks_data(self, days=60):
        """Scrape multiple stocks data"""
        try:
            logger.info("   🔑 Getting CSRF token from API...")
            csrf_token = self._get_csrf_token()
            if not csrf_token:
                logger.error("❌ Failed to get CSRF token")
                return None

            logger.info(f"   📡 Fetching stock data for {days} days from API...")
            response = self.session.post(
                f"{self.base_url}/stocks/",
                data={"days": str(days), "csrf": csrf_token},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json().get("data", [])
                logger.info(f"   ✅ Received {len(data)} stocks from API")
                return data
            else:
                logger.error(f"❌ Stocks API returned status {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Request failed: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Unexpected error: {str(e)}")
        
        return None

    def scrape_single_stock(self, symbol):
        """Scrape data for a single stock"""
        try:
            csrf_token = self._get_csrf_token()
            if not csrf_token:
                logger.error(f"Failed to get CSRF token for {symbol}")
                return None

            response = self.session.post(
                f"{self.base_url}/stocks/",
                data={"symbol": symbol, "csrf": csrf_token},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                # Handle different response formats
                if isinstance(data, list):
                    return data[0] if data else None
                return data.get('data', [])[0] if data.get('data') else None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {symbol}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error for {symbol}: {str(e)}")
        
        return None

    def _parse_decimal(self, value):
        """Safely parse decimal values"""
        if not value or value == "N/A":
            return None
        try:
            # Remove percentage signs and commas
            if isinstance(value, str):
                value = value.replace('%', '').replace(',', '').strip()
            return Decimal(value)
        except (ValueError, TypeError, AttributeError):
            logger.debug(f"Failed to parse decimal: {value}")
            return None

    def _parse_float(self, value):
        """Safely parse float values"""
        if not value or value == "N/A":
            return None
        try:
            if isinstance(value, str):
                value = value.replace('%', '').replace(',', '').strip()
            return float(value)
        except (ValueError, TypeError, AttributeError):
            logger.debug(f"Failed to parse float: {value}")
            return None

    def _parse_int(self, value):
        """Safely parse integer values"""
        if not value or value == "N/A":
            return None
        try:
            if isinstance(value, str):
                value = value.replace(',', '').strip()
            return int(value)
        except (ValueError, TypeError, AttributeError):
            logger.debug(f"Failed to parse int: {value}")
            return None

    def _parse_market_cap(self, market_cap_str):
        """Parse market cap string like '1.3B' into a numeric value"""
        if not market_cap_str or market_cap_str == "N/A":
            return None
        
        try:
            market_cap_str = market_cap_str.upper().strip()
            if 'B' in market_cap_str:
                return float(market_cap_str.replace('B', '')) * 1_000_000_000
            elif 'M' in market_cap_str:
                return float(market_cap_str.replace('M', '')) * 1_000_000
            elif 'K' in market_cap_str:
                return float(market_cap_str.replace('K', '')) * 1_000
            else:
                return float(market_cap_str)
        except (ValueError, TypeError, AttributeError):
            logger.debug(f"Failed to parse market cap: {market_cap_str}")
            return None

    def transform_stock_data(self, raw_data):
        """Transform raw API data into our database format"""
        if not raw_data:
            return None

        try:
            # Extract analyst ratings from the aggregate string
            analyst_aggregate = raw_data.get('analyst_aggregate', '')
            buy_count = hold_count = sell_count = None
            
            if analyst_aggregate:
                try:
                    # Parse "Buy: 5 - Hold: 3 - Sell: 2" format
                    parts = analyst_aggregate.split(' - ')
                    for part in parts:
                        if 'Buy:' in part:
                            buy_count = self._parse_int(part.replace('Buy:', '').strip())
                        elif 'Hold:' in part:
                            hold_count = self._parse_int(part.replace('Hold:', '').strip())
                        elif 'Sell:' in part:
                            sell_count = self._parse_int(part.replace('Sell:', '').strip())
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug(f"Failed to parse analyst aggregate: {analyst_aggregate}, error: {e}")
                    pass

            transformed = {
                'symbol': raw_data.get('symbol') or raw_data.get('code', ''),
                'code': raw_data.get('code') or raw_data.get('symbol', ''),
                'company_name': raw_data.get('company') or raw_data.get('name', ''),
                'last_price': self._parse_decimal(raw_data.get('last_price')),
                'volume': self._parse_int(raw_data.get('volume')),
                'fiftytwo_week_high': self._parse_decimal(raw_data.get('fiftytwoh')),
                'fiftytwo_week_low': self._parse_decimal(raw_data.get('fiftytwol')),
                'dividend_amount': self._parse_decimal(raw_data.get('dividend')),
                'dividend_yield': self._parse_decimal(raw_data.get('yield')),
                'dividend_frequency': raw_data.get('payout_frequency', ''),
                'dividend_date': raw_data.get('dividend_date'),
                'dividend_payable_date': raw_data.get('dividend_payable_date'),
                'pe_ratio': self._parse_decimal(raw_data.get('pe_ratio')),
                'eps': self._parse_decimal(raw_data.get('eps')),
                'market_cap': raw_data.get('market_cap', ''),
                'analyst_aggregate': analyst_aggregate,
                'analyst_rating': raw_data.get('analyst_rating', ''),
                'analyst_buy': buy_count,
                'analyst_hold': hold_count,
                'analyst_sell': sell_count,
                'growth_3_year': self._parse_decimal(raw_data.get('growth_3')),
                'growth_5_year': self._parse_decimal(raw_data.get('growth_5')),
                'is_etf': bool(raw_data.get('etf', 0)),
                'market_index': raw_data.get('market_index'),
                'tsx60_member': bool(raw_data.get('tsx60', 0)),
                'industry': raw_data.get('industry', ''),
                'sector': raw_data.get('sector', ''),
                'currency': raw_data.get('dividend_currency', 'CAD')
            }
            
            return transformed
            
        except Exception as e:
            logger.error(f"Error transforming stock data: {str(e)}")
            return None

    def update_stock_in_database(self, transformed_data):
        """Update stock data in Django database - optimized for single stock"""
        try:
            symbol = transformed_data['symbol']
            if not symbol:
                return False, "No symbol provided"

            with transaction.atomic():
                # Get or create stock
                stock, created = Stock.objects.update_or_create(
                    symbol=symbol,
                    defaults={
                        'code': transformed_data['code'],
                        'company_name': transformed_data['company_name'],
                        'is_etf': transformed_data['is_etf'],
                        'tsx60_member': transformed_data['tsx60_member'],
                        'industry': transformed_data['industry'],
                        'sector': transformed_data['sector']
                    }
                )

                today = date.today()

                # Update stock price - optimized query
                if transformed_data['last_price'] is not None:
                    # Use get_or_create to avoid separate query
                    latest_price, _ = StockPrice.objects.get_or_create(
                        stock=stock,
                        price_date=today,
                        defaults={
                            'last_price': transformed_data['last_price'],
                            'volume': transformed_data['volume'],
                            'fiftytwo_week_high': transformed_data['fiftytwo_week_high'],
                            'fiftytwo_week_low': transformed_data['fiftytwo_week_low'],
                            'currency': transformed_data['currency']
                        }
                    )
                    
                    # Update if record already exists for today
                    if not _:
                        latest_price.last_price = transformed_data['last_price']
                        latest_price.volume = transformed_data['volume']
                        latest_price.fiftytwo_week_high = transformed_data['fiftytwo_week_high']
                        latest_price.fiftytwo_week_low = transformed_data['fiftytwo_week_low']
                        latest_price.currency = transformed_data['currency']
                        latest_price.save(update_fields=['last_price', 'volume', 'fiftytwo_week_high', 'fiftytwo_week_low', 'currency'])

                # Update dividend information - maintains history by ex_dividend_date
                if (transformed_data['dividend_amount'] is not None and 
                    transformed_data['dividend_date']):
                    
                    try:
                        if isinstance(transformed_data['dividend_date'], str):
                            ex_dividend_date = datetime.strptime(transformed_data['dividend_date'], '%Y-%m-%d').date()
                        else:
                            ex_dividend_date = transformed_data['dividend_date']
                    except (ValueError, TypeError) as e:
                        logger.error(f"Error parsing dividend date for {symbol}: {str(e)}")
                        ex_dividend_date = None
                        
                    if ex_dividend_date:
                        frequency = transformed_data['dividend_frequency']
                        if not frequency or frequency == 'N/A':
                            frequency = 'Unknown'
                        
                        payment_date = None
                        if transformed_data['dividend_payable_date']:
                            try:
                                if isinstance(transformed_data['dividend_payable_date'], str):
                                    payment_date = datetime.strptime(transformed_data['dividend_payable_date'], '%Y-%m-%d').date()
                                else:
                                    payment_date = transformed_data['dividend_payable_date']
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error parsing payment date for {symbol}: {str(e)}")
                                payment_date = None
                        
                        # Update or create dividend
                        Dividend.objects.update_or_create(
                            stock=stock,
                            ex_dividend_date=ex_dividend_date,
                            defaults={
                                'amount': transformed_data['dividend_amount'],
                                'yield_percent': transformed_data['dividend_yield'],
                                'frequency': frequency,
                                'payment_date': payment_date,
                                'currency': transformed_data['currency']
                            }
                        )

                # Update valuation metrics - use get_or_create
                ValuationMetric.objects.update_or_create(
                    stock=stock,
                    metric_date=today,
                    defaults={
                        'pe_ratio': transformed_data['pe_ratio'],
                        'eps': transformed_data['eps'],
                        'market_cap': transformed_data['market_cap'],
                        'growth_3_year': transformed_data['growth_3_year'],
                        'growth_5_year': transformed_data['growth_5_year']
                    }
                )

                # Update analyst ratings - use get_or_create
                AnalystRating.objects.update_or_create(
                    stock=stock,
                    rating_date=today,
                    defaults={
                        'aggregate_rating': transformed_data['analyst_aggregate'],
                        'analyst_rating': transformed_data['analyst_rating'],
                        'buy_count': transformed_data['analyst_buy'],
                        'hold_count': transformed_data['analyst_hold'],
                        'sell_count': transformed_data['analyst_sell']
                    }
                )

            return True, f"Successfully updated {symbol}"
            
        except Exception as e:
            logger.error(f"Database update error for {transformed_data.get('symbol', 'unknown')}: {str(e)}")
            return False, f"Database error: {str(e)}"

    def update_daily_stocks(self, symbols=None, days=60, batch_size=50):
        """
        Main method to update stocks daily
        Optimized with batch processing and connection management
        """
        results = []
        
        # If no symbols provided, scrape all stocks
        if not symbols:
            logger.info(f"📊 Scraping all stocks for next {days} days...")
            logger.info("🔄 Fetching stock data from API...")
            
            raw_stocks_data = self.scrape_stocks_data(days)
            if not raw_stocks_data:
                logger.error("❌ Failed to scrape stocks data from API")
                return [{'success': False, 'message': 'Failed to scrape stocks data'}]
            
            logger.info(f"✅ Fetched {len(raw_stocks_data)} stocks from API")
            logger.info("🔄 Transforming stock data...")
            
            # Process in batches to optimize database connections
            transformed_list = []
            transform_count = 0
            for idx, raw_data in enumerate(raw_stocks_data, 1):
                transformed = self.transform_stock_data(raw_data)
                if transformed:
                    transformed_list.append(transformed)
                    transform_count += 1
                
                # Log transformation progress every 50 stocks
                if idx % 50 == 0:
                    logger.info(f"   Transformed {idx}/{len(raw_stocks_data)} stocks...")
            
            logger.info(f"✅ Transformed {transform_count} stocks successfully")
            
            # Process in batches
            total = len(transformed_list)
            logger.info(f"💾 Processing {total} stocks in batches of {batch_size}...")
            
            for i in range(0, total, batch_size):
                batch = transformed_list[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (total + batch_size - 1) // batch_size
                
                logger.info(f"📦 Processing batch {batch_num}/{total_batches} ({len(batch)} stocks)...")
                batch_results = self._process_batch(batch)
                results.extend(batch_results)
                
                # Count successes in this batch
                batch_success = sum(1 for r in batch_results if r['success'])
                batch_failed = len(batch_results) - batch_success
                
                # Log progress
                processed = min(i + batch_size, total)
                logger.info(f"   ✅ Batch {batch_num} complete: {batch_success} success, {batch_failed} failed")
                logger.info(f"📊 Overall progress: {processed}/{total} stocks ({processed*100//total}%)")
                
                # Close database connections between batches to free resources
                connection.close()
        else:
            # Update specific symbols
            for symbol in symbols:
                logger.info(f"Scraping symbol: {symbol}")
                raw_data = self.scrape_single_stock(symbol)
                if raw_data:
                    transformed = self.transform_stock_data(raw_data)
                    if transformed:
                        success, message = self.update_stock_in_database(transformed)
                        results.append({
                            'symbol': symbol,
                            'success': success,
                            'message': message
                        })
                        # Close connection after each symbol to free resources
                        connection.close()
                else:
                    results.append({
                        'symbol': symbol,
                        'success': False,
                        'message': f"Failed to scrape data for {symbol}"
                    })
        
        return results
    
    def _process_batch(self, transformed_list):
        """
        Process a batch of stocks with optimized database operations
        Uses bulk operations where possible
        """
        results = []
        
        if not transformed_list:
            return results
        
        try:
            logger.info(f"   🔄 Processing batch of {len(transformed_list)} stocks...")
            
            with transaction.atomic():
                # Pre-fetch existing stocks to reduce queries
                symbols = [t['symbol'].upper() for t in transformed_list]
                existing_stocks = {
                    s.symbol.upper(): s 
                    for s in Stock.objects.filter(symbol__in=symbols)
                }
                logger.debug(f"   ✅ Found {len(existing_stocks)} existing stocks")
                
                # Prepare stock updates/creates
                stocks_to_create = []
                stocks_to_update = []
                today = date.today()
                
                for transformed in transformed_list:
                    symbol = transformed['symbol'].upper()
                    
                    if symbol in existing_stocks:
                        # Update existing stock
                        stock = existing_stocks[symbol]
                        stock.code = transformed['code']
                        stock.company_name = transformed['company_name']
                        stock.is_etf = transformed['is_etf']
                        stock.tsx60_member = transformed['tsx60_member']
                        stock.industry = transformed['industry']
                        stock.sector = transformed['sector']
                        stocks_to_update.append(stock)
                    else:
                        # Create new stock
                        stocks_to_create.append(Stock(
                            symbol=symbol,
                            code=transformed['code'],
                            company_name=transformed['company_name'],
                            is_etf=transformed['is_etf'],
                            tsx60_member=transformed['tsx60_member'],
                            industry=transformed['industry'],
                            sector=transformed['sector']
                        ))
                
                # Bulk create new stocks
                if stocks_to_create:
                    logger.info(f"   ➕ Creating {len(stocks_to_create)} new stocks...")
                    Stock.objects.bulk_create(stocks_to_create, ignore_conflicts=True)
                
                # Bulk update existing stocks
                if stocks_to_update:
                    logger.info(f"   🔄 Updating {len(stocks_to_update)} existing stocks...")
                    Stock.objects.bulk_update(
                        stocks_to_update,
                        ['code', 'company_name', 'is_etf', 'tsx60_member', 'industry', 'sector']
                    )
                
                # Refresh existing_stocks dict with newly created stocks
                all_stocks = {
                    s.symbol.upper(): s 
                    for s in Stock.objects.filter(symbol__in=symbols)
                }
                
                # Process each stock's related data
                logger.info(f"   💾 Processing related data (prices, dividends, metrics)...")
                processed_count = 0
                for idx, transformed in enumerate(transformed_list, 1):
                    symbol = transformed['symbol'].upper()
                    stock = all_stocks.get(symbol)
                    
                    if not stock:
                        results.append({
                            'symbol': symbol,
                            'success': False,
                            'message': 'Failed to get/create stock'
                        })
                        continue
                    
                    # Process individual stock data (prices, dividends, etc.)
                    # This still uses individual operations for related models
                    # as they have complex relationships
                    success, message = self._update_stock_related_data(stock, transformed, today)
                    results.append({
                        'symbol': symbol,
                        'success': success,
                        'message': message
                    })
                    processed_count += 1
                    
                    # Log every 10 stocks in batch
                    if idx % 10 == 0:
                        logger.info(f"      ✓ Processed {idx}/{len(transformed_list)} stocks...")
                
                logger.info(f"   ✅ Completed processing {processed_count} stocks in batch")
        
        except Exception as e:
            logger.error(f"Batch processing error: {str(e)}")
            # Fallback to individual processing
            for transformed in transformed_list:
                try:
                    success, message = self.update_stock_in_database(transformed)
                    results.append({
                        'symbol': transformed['symbol'],
                        'success': success,
                        'message': message
                    })
                except Exception as e2:
                    results.append({
                        'symbol': transformed.get('symbol', 'unknown'),
                        'success': False,
                        'message': f"Error: {str(e2)}"
                    })
        
        return results
    
    def _update_stock_related_data(self, stock, transformed_data, today):
        """Update related data for a stock (prices, dividends, metrics, ratings)"""
        try:
            # Update stock price
            if transformed_data['last_price'] is not None:
                StockPrice.objects.update_or_create(
                    stock=stock,
                    price_date=today,
                    defaults={
                        'last_price': transformed_data['last_price'],
                        'volume': transformed_data['volume'],
                        'fiftytwo_week_high': transformed_data['fiftytwo_week_high'],
                        'fiftytwo_week_low': transformed_data['fiftytwo_week_low'],
                        'currency': transformed_data['currency']
                    }
                )

            # Update dividend
            if (transformed_data['dividend_amount'] is not None and 
                transformed_data['dividend_date']):
                
                try:
                    if isinstance(transformed_data['dividend_date'], str):
                        ex_dividend_date = datetime.strptime(transformed_data['dividend_date'], '%Y-%m-%d').date()
                    else:
                        ex_dividend_date = transformed_data['dividend_date']
                except (ValueError, TypeError):
                    ex_dividend_date = None
                    
                if ex_dividend_date:
                    frequency = transformed_data['dividend_frequency']
                    if not frequency or frequency == 'N/A':
                        frequency = 'Unknown'
                    
                    payment_date = None
                    if transformed_data['dividend_payable_date']:
                        try:
                            if isinstance(transformed_data['dividend_payable_date'], str):
                                payment_date = datetime.strptime(transformed_data['dividend_payable_date'], '%Y-%m-%d').date()
                            else:
                                payment_date = transformed_data['dividend_payable_date']
                        except (ValueError, TypeError):
                            payment_date = None
                    
                    Dividend.objects.update_or_create(
                        stock=stock,
                        ex_dividend_date=ex_dividend_date,
                        defaults={
                            'amount': transformed_data['dividend_amount'],
                            'yield_percent': transformed_data['dividend_yield'],
                            'frequency': frequency,
                            'payment_date': payment_date,
                            'currency': transformed_data['currency']
                        }
                    )

            # Update valuation metrics
            ValuationMetric.objects.update_or_create(
                stock=stock,
                metric_date=today,
                defaults={
                    'pe_ratio': transformed_data['pe_ratio'],
                    'eps': transformed_data['eps'],
                    'market_cap': transformed_data['market_cap'],
                    'growth_3_year': transformed_data['growth_3_year'],
                    'growth_5_year': transformed_data['growth_5_year']
                }
            )

            # Update analyst ratings
            AnalystRating.objects.update_or_create(
                stock=stock,
                rating_date=today,
                defaults={
                    'aggregate_rating': transformed_data['analyst_aggregate'],
                    'analyst_rating': transformed_data['analyst_rating'],
                    'buy_count': transformed_data['analyst_buy'],
                    'hold_count': transformed_data['analyst_hold'],
                    'sell_count': transformed_data['analyst_sell']
                }
            )

            return True, f"Successfully updated {stock.symbol}"
            
        except Exception as e:
            logger.error(f"Error updating related data for {stock.symbol}: {str(e)}")
            return False, f"Error: {str(e)}"