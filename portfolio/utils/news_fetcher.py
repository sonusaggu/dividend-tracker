"""
News fetching utility for stocks
Uses free news APIs to fetch news articles for stocks
"""
import requests
import logging
import time
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from decouple import config
from portfolio.models import Stock, StockNews

logger = logging.getLogger(__name__)


class NewsFetcher:
    """Fetches news articles for stocks using free APIs"""
    
    def __init__(self):
        # Try to get API key from settings, fallback to environment variable
        self.newsapi_key = config('NEWSAPI_KEY', default='')
        self.alpha_vantage_key = config('ALPHA_VANTAGE_KEY', default='')
        # Rate limiting: track last API call time
        self.last_newsapi_call = 0
        self.last_alphavantage_call = 0
        self.min_delay_between_calls = 1.0  # Minimum 1 second between API calls
        self.rate_limit_hit = False
        
    def fetch_news_for_stock(self, stock, max_articles=10):
        """
        Fetch news for a single stock
        Returns list of news articles
        Reduced max_articles default to 10 to reduce API calls
        """
        articles = []
        
        # Check if API keys are configured
        if not self.newsapi_key and not self.alpha_vantage_key:
            logger.warning(f"No news API keys configured. Set NEWSAPI_KEY or ALPHA_VANTAGE_KEY environment variables.")
            return articles
        
        # Check if we've hit rate limit - skip if so
        if self.rate_limit_hit:
            logger.warning(f"Skipping {stock.symbol} - rate limit already hit")
            return articles
        
        # Check if news was recently fetched (within last 24 hours) to avoid redundant calls
        recent_news = StockNews.objects.filter(
            stock=stock,
            published_at__gte=timezone.now() - timedelta(days=1)
        ).exists()
        
        if recent_news:
            logger.debug(f"Skipping {stock.symbol} - news was recently fetched")
            return articles
        
        # Try NewsAPI first (free tier: 100 requests/day)
        if self.newsapi_key and not self.rate_limit_hit:
            try:
                # Rate limiting: wait if needed
                self._wait_for_rate_limit('newsapi')
                
                logger.debug(f"Fetching from NewsAPI for {stock.symbol}")
                newsapi_articles = self._fetch_from_newsapi(stock, max_articles)
                articles.extend(newsapi_articles)
                logger.debug(f"NewsAPI returned {len(newsapi_articles)} articles for {stock.symbol}")
                
                # Update last call time
                self.last_newsapi_call = time.time()
            except Exception as e:
                error_msg = str(e).lower()
                if '429' in error_msg or 'rate limit' in error_msg:
                    logger.warning(f"NewsAPI rate limit hit for {stock.symbol}")
                    self.rate_limit_hit = True
                else:
                    logger.warning(f"NewsAPI fetch failed for {stock.symbol}: {e}")
        
        # Try Alpha Vantage as fallback (free tier: 5 API calls/min, 500/day)
        # Only if we don't have enough articles and haven't hit rate limit
        if len(articles) < max_articles and self.alpha_vantage_key and not self.rate_limit_hit:
            try:
                # Rate limiting: wait if needed (Alpha Vantage needs 12 seconds between calls for free tier)
                self._wait_for_rate_limit('alphavantage', min_delay=12.0)
                
                logger.debug(f"Fetching from Alpha Vantage for {stock.symbol}")
                av_articles = self._fetch_from_alphavantage(stock, max_articles - len(articles))
                articles.extend(av_articles)
                logger.debug(f"Alpha Vantage returned {len(av_articles)} articles for {stock.symbol}")
                
                # Update last call time
                self.last_alphavantage_call = time.time()
            except Exception as e:
                error_msg = str(e).lower()
                if '429' in error_msg or 'rate limit' in error_msg:
                    logger.warning(f"Alpha Vantage rate limit hit for {stock.symbol}")
                    self.rate_limit_hit = True
                else:
                    logger.warning(f"Alpha Vantage fetch failed for {stock.symbol}: {e}")
        
        # Don't use generic fallback to avoid extra API calls
        
        if not articles:
            logger.debug(f"No news articles found for {stock.symbol} from any source")
        
        return articles[:max_articles]
    
    def _wait_for_rate_limit(self, api_name, min_delay=None):
        """Wait if needed to respect rate limits"""
        if min_delay is None:
            min_delay = self.min_delay_between_calls
        
        if api_name == 'newsapi':
            elapsed = time.time() - self.last_newsapi_call
            if elapsed < min_delay:
                wait_time = min_delay - elapsed
                logger.debug(f"Rate limiting: waiting {wait_time:.2f}s before NewsAPI call")
                time.sleep(wait_time)
        elif api_name == 'alphavantage':
            elapsed = time.time() - self.last_alphavantage_call
            if elapsed < min_delay:
                wait_time = min_delay - elapsed
                logger.debug(f"Rate limiting: waiting {wait_time:.2f}s before Alpha Vantage call")
                time.sleep(wait_time)
    
    def _fetch_from_newsapi(self, stock, max_articles=20):
        """Fetch news from NewsAPI.org with improved relevance"""
        articles = []
        
        # Build more specific search query for better relevance
        # Use quotes for exact matches and add stock-related keywords
        symbol = stock.symbol.upper()
        company_name = stock.company_name or ''
        
        # Create multiple search queries for better results
        queries = [
            f'"{symbol}" stock',  # Exact symbol match with "stock"
            f'{symbol} TSX',  # Symbol with TSX exchange
        ]
        
        # Add company name query only if available
        if company_name:
            queries.insert(1, f'"{company_name}" stock')
            queries.append(f'"{symbol}" dividend')
        
        all_articles = []
        
        # Try only ONE query to reduce API calls and avoid rate limits
        for query in queries[:1]:  # Limit to 1 query to avoid rate limits
            try:
                url = "https://newsapi.org/v2/everything"
                params = {
                    'q': query,
                    'language': 'en',
                    'sortBy': 'relevancy',  # Sort by relevance instead of date
                    'pageSize': min(max_articles, 20),
                    'apiKey': self.newsapi_key
                }
                
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                # Check for API errors
                if data.get('status') == 'error':
                    error_message = data.get('message', 'Unknown error')
                    if 'rate limit' in error_message.lower() or '429' in str(response.status_code):
                        logger.warning(f"NewsAPI rate limit reached for {stock.symbol}")
                        break  # Stop trying more queries if rate limited
                    logger.warning(f"NewsAPI error for {stock.symbol}: {error_message}")
                    continue
                
                if data.get('status') == 'ok':
                    for article in data.get('articles', []):
                        if not article.get('url') or not article.get('title'):
                            continue
                            
                        title = article.get('title', '').lower()
                        description = article.get('description', '').lower()
                        content = f"{title} {description}"
                        
                        # Filter for relevance - must mention symbol or company name
                        if symbol.lower() in content or (company_name and company_name.lower() in content):
                            # Skip if it's clearly not about this stock
                            if self._is_relevant_article(article, stock):
                                all_articles.append({
                                    'title': article.get('title', ''),
                                    'description': article.get('description', ''),
                                    'url': article.get('url', ''),
                                    'source': article.get('source', {}).get('name', 'Unknown'),
                                    'author': article.get('author', ''),
                                    'published_at': self._parse_date(article.get('publishedAt')),
                                    'image_url': article.get('urlToImage', ''),
                                    'relevance_score': self._calculate_relevance(article, stock),
                                })
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    logger.warning(f"NewsAPI rate limit (429) for {stock.symbol}")
                    break
                logger.warning(f"NewsAPI HTTP error for '{query}': {e}")
                continue
            except Exception as e:
                logger.warning(f"NewsAPI query failed for '{query}': {e}")
                continue
        
        # Sort by relevance score and remove duplicates by URL
        seen_urls = set()
        for article in sorted(all_articles, key=lambda x: x.get('relevance_score', 0), reverse=True):
            if article['url'] not in seen_urls:
                seen_urls.add(article['url'])
                articles.append(article)
                if len(articles) >= max_articles:
                    break
        
        return articles
    
    def _is_relevant_article(self, article, stock):
        """Check if article is relevant to the stock"""
        title = (article.get('title', '') or '').lower()
        description = (article.get('description', '') or '').lower()
        content = f"{title} {description}"
        
        symbol = stock.symbol.lower()
        company_name = (stock.company_name or '').lower()
        
        # Must contain symbol or company name
        if symbol not in content and (not company_name or company_name not in content):
            return False
        
        # Exclude common false positives
        exclude_keywords = ['cryptocurrency', 'crypto', 'forex', 'currency', 'bitcoin', 'ethereum']
        for keyword in exclude_keywords:
            if keyword in content and symbol not in content:
                return False
        
        return True
    
    def _calculate_relevance(self, article, stock):
        """Calculate relevance score for an article"""
        score = 0
        title = (article.get('title', '') or '').lower()
        description = (article.get('description', '') or '').lower()
        content = f"{title} {description}"
        
        symbol = stock.symbol.lower()
        company_name = stock.company_name.lower()
        
        # Higher score for symbol mentions (more specific)
        if symbol in title:
            score += 10
        elif symbol in description:
            score += 5
        
        # Company name mentions
        if company_name in title:
            score += 8
        elif company_name in description:
            score += 4
        
        # Financial keywords boost relevance
        financial_keywords = ['dividend', 'earnings', 'revenue', 'profit', 'stock', 'shares', 'tsx', 'tse']
        for keyword in financial_keywords:
            if keyword in content:
                score += 2
        
        return score
    
    def _fetch_from_alphavantage(self, stock, max_articles=20):
        """Fetch news from Alpha Vantage with relevance filtering"""
        articles = []
        
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'NEWS_SENTIMENT',
            'tickers': stock.symbol,
            'limit': min(max_articles * 2, 50),  # Fetch more to filter for relevance
            'apikey': self.alpha_vantage_key
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Check for Alpha Vantage API errors
            if 'Error Message' in data:
                logger.warning(f"Alpha Vantage error for {stock.symbol}: {data['Error Message']}")
                return articles
            if 'Note' in data:
                logger.warning(f"Alpha Vantage note for {stock.symbol}: {data['Note']}")
                return articles
            
            if 'feed' in data and isinstance(data['feed'], list):
                for item in data['feed']:
                    if not item.get('url') or not item.get('title'):
                        continue
                    
                    # Check if article mentions this specific ticker
                    tickers = item.get('ticker_sentiment', [])
                    relevant_ticker = False
                    
                    if isinstance(tickers, list):
                        for ticker_info in tickers:
                            if isinstance(ticker_info, dict) and ticker_info.get('ticker', '').upper() == stock.symbol.upper():
                                relevant_ticker = True
                                break
                    
                    # Only include if it's about this specific stock
                    if not relevant_ticker:
                        continue
                    
                    # Parse sentiment
                    sentiment = 'neutral'
                    if 'overall_sentiment_score' in item:
                        try:
                            score = float(item.get('overall_sentiment_score', 0))
                            if score > 0.1:
                                sentiment = 'positive'
                            elif score < -0.1:
                                sentiment = 'negative'
                        except (ValueError, TypeError):
                            pass
                    
                    article_data = {
                        'title': item.get('title', ''),
                        'description': item.get('summary', ''),
                        'url': item.get('url', ''),
                        'source': item.get('source', 'Unknown'),
                        'author': '',
                        'published_at': self._parse_date(item.get('time_published')),
                        'image_url': item.get('banner_image', ''),
                        'sentiment': sentiment,
                    }
                    
                    # Additional relevance check
                    if self._is_relevant_article(article_data, stock):
                        article_data['relevance_score'] = self._calculate_relevance(article_data, stock)
                        articles.append(article_data)
            
            # Sort by relevance and limit
            articles.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
            return articles[:max_articles]
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning(f"Alpha Vantage rate limit (429) for {stock.symbol}")
            else:
                logger.error(f"Alpha Vantage HTTP error for {stock.symbol}: {e}")
            return articles
        except Exception as e:
            logger.error(f"Alpha Vantage error for {stock.symbol}: {e}")
            return articles
    
    def _fetch_generic_news(self, stock, max_articles=10):
        """
        Fallback: Use web scraping or RSS feeds
        This is a placeholder - can be enhanced with RSS feeds
        """
        articles = []
        
        # For now, return empty list
        # Can be enhanced with RSS feeds from financial news sites
        # or web scraping (respecting robots.txt)
        
        return articles
    
    def _parse_date(self, date_string):
        """Parse various date formats to datetime"""
        if not date_string:
            return timezone.now()
        
        # Convert to string if not already
        if not isinstance(date_string, str):
            date_string = str(date_string)
        
        # Try different date formats
        formats = [
            '%Y-%m-%dT%H:%M:%SZ',  # NewsAPI format: 2024-01-15T12:00:00Z
            '%Y-%m-%dT%H:%M:%S%z',  # With timezone: 2024-01-15T12:00:00+00:00
            '%Y-%m-%dT%H:%M:%S',    # Without timezone: 2024-01-15T12:00:00
            '%Y-%m-%d %H:%M:%S',    # Space separated: 2024-01-15 12:00:00
            '%Y%m%dT%H%M%S',        # Alpha Vantage format: 20240115T120000
            '%Y-%m-%d',             # Date only: 2024-01-15
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_string, fmt)
                if dt.tzinfo is None:
                    dt = timezone.make_aware(dt)
                return dt
            except ValueError:
                continue
        
        # If all formats fail, return current time
        logger.warning(f"Could not parse date: {date_string}")
        return timezone.now()
    
    def save_news_to_database(self, stock, articles, max_age_days=7, min_relevance_score=0):
        """
        Save news articles to database, avoiding duplicates
        Only saves articles from the last max_age_days and with minimum relevance
        """
        saved_count = 0
        cutoff_date = timezone.now() - timedelta(days=max_age_days)
        
        for article in articles:
            # Filter by minimum relevance score if available
            relevance_score = article.get('relevance_score', 0)
            if relevance_score < min_relevance_score:
                continue
            # Validate required fields
            if not article or not isinstance(article, dict):
                continue
            
            # Skip if missing required fields
            if not article.get('url') or not article.get('title'):
                continue
            
            # Skip if published_at is missing or invalid
            published_at = article.get('published_at')
            if not published_at:
                continue
            
            # Skip if article is too old
            if published_at < cutoff_date:
                continue
            
            # Check if article already exists (by URL)
            url = article.get('url', '').strip()
            if not url:
                continue
            
            # Validate URL format
            if not url.startswith(('http://', 'https://')):
                logger.warning(f"Invalid URL format: {url}")
                continue
                
            existing = StockNews.objects.filter(url=url).first()
            if existing:
                continue
            
            try:
                # Safely extract and truncate fields (exclude relevance_score as it's not a model field)
                title = (article.get('title') or 'Untitled')[:500]
                description = (article.get('description') or '')[:2000]
                source = (article.get('source') or '')[:100]
                author = (article.get('author') or '')[:200]
                image_url = (article.get('image_url') or '')[:1000]
                sentiment = (article.get('sentiment') or '')[:20]
                
                StockNews.objects.create(
                    stock=stock,
                    title=title,
                    description=description,
                    url=url,
                    source=source,
                    author=author,
                    published_at=published_at,
                    image_url=image_url,
                    sentiment=sentiment,
                )
                saved_count += 1
                logger.debug(f"Saved news article: {title[:50]}... (relevance: {relevance_score})")
            except Exception as e:
                logger.error(f"Error saving news article: {e}")
                logger.debug(f"Article data: {article}")
                continue
        
        return saved_count
    
    def fetch_and_save_news(self, stocks, max_articles_per_stock=5, max_age_days=7):
        """
        Fetch and save news for multiple stocks
        Returns summary of saved articles
        Reduced default max_articles_per_stock to 5 to reduce API calls
        """
        total_saved = 0
        stocks_processed = 0
        
        for stock in stocks:
            # Stop if rate limit was hit
            if self.rate_limit_hit:
                logger.warning(f"Rate limit hit. Stopping news fetching. Processed {stocks_processed} stocks.")
                break
            
            try:
                articles = self.fetch_news_for_stock(stock, max_articles_per_stock)
                saved = self.save_news_to_database(stock, articles, max_age_days)
                total_saved += saved
                stocks_processed += 1
                logger.info(f"Saved {saved} news articles for {stock.symbol}")
                
                # Add delay between stocks to avoid rate limits (2 seconds between stocks)
                if stocks_processed < len(list(stocks)):
                    time.sleep(2.0)
                    
            except Exception as e:
                error_msg = str(e).lower()
                if '429' in error_msg or 'rate limit' in error_msg:
                    logger.warning(f"Rate limit hit while processing {stock.symbol}")
                    self.rate_limit_hit = True
                    break
                logger.error(f"Error fetching news for {stock.symbol}: {e}")
                continue
        
        return total_saved

