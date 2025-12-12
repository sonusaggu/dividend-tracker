"""
Utility to update analyst ratings based on positive news sentiment
"""
from django.utils import timezone
from django.db import models
from datetime import timedelta
from portfolio.models import Stock, AnalystRating, StockNews
import logging

logger = logging.getLogger(__name__)


def calculate_rating_adjustment_from_news(stock, days=7):
    """
    Calculate how analyst ratings should be adjusted based on recent positive news
    
    Args:
        stock: Stock instance
        days: Number of days to look back for news (default: 7)
    
    Returns:
        dict with adjustment values for buy_count, hold_count, sell_count
    """
    cutoff_date = timezone.now() - timedelta(days=days)
    
    # Get recent news with sentiment
    recent_news = StockNews.objects.filter(
        stock=stock,
        published_at__gte=cutoff_date,
        sentiment__in=['positive', 'negative']
    ).order_by('-published_at')
    
    if not recent_news.exists():
        return None
    
    # Count positive vs negative news
    positive_count = recent_news.filter(sentiment='positive').count()
    negative_count = recent_news.filter(sentiment='negative').count()
    total_news = recent_news.count()
    
    # Calculate sentiment score (-1 to 1, where 1 is all positive)
    if total_news == 0:
        return None
    
    sentiment_score = (positive_count - negative_count) / total_news
    
    # Only adjust if there's a strong positive sentiment (>= 0.6)
    if sentiment_score >= 0.6 and positive_count >= 2:
        # Calculate adjustments based on sentiment strength
        # Strong positive news increases buy count, decreases sell count
        adjustment_factor = min(sentiment_score, 0.9)  # Cap at 0.9
        
        # More positive news = more buy adjustments
        buy_adjustment = max(1, int(positive_count * adjustment_factor))
        sell_adjustment = -max(0, int(negative_count * 0.5))  # Reduce sell count slightly
        
        return {
            'buy_adjustment': buy_adjustment,
            'hold_adjustment': 0,  # Hold stays neutral
            'sell_adjustment': sell_adjustment,
            'sentiment_score': sentiment_score,
            'positive_news_count': positive_count,
            'negative_news_count': negative_count,
        }
    
    return None


def update_analyst_rating_from_news(stock, days=7, min_positive_news=2):
    """
    Update analyst rating for a stock based on recent positive news
    
    Args:
        stock: Stock instance
        days: Number of days to look back for news
        min_positive_news: Minimum number of positive news articles required
    
    Returns:
        tuple: (success: bool, message: str, updated_rating: AnalystRating or None)
    """
    try:
        # Get current rating
        today = timezone.now().date()
        current_rating = AnalystRating.objects.filter(
            stock=stock,
            rating_date__lte=today
        ).order_by('-rating_date').first()
        
        if not current_rating:
            return False, "No existing analyst rating found", None
        
        # Calculate adjustment from news
        adjustment = calculate_rating_adjustment_from_news(stock, days)
        
        if not adjustment:
            return False, "Insufficient positive news to adjust rating", None
        
        if adjustment['positive_news_count'] < min_positive_news:
            return False, f"Need at least {min_positive_news} positive news articles", None
        
        # Create or update rating with adjusted values
        new_buy_count = (current_rating.buy_count or 0) + adjustment['buy_adjustment']
        new_hold_count = max(0, (current_rating.hold_count or 0) + adjustment['hold_adjustment'])
        new_sell_count = max(0, (current_rating.sell_count or 0) + adjustment['sell_adjustment'])
        
        # Ensure counts don't go negative
        new_buy_count = max(0, new_buy_count)
        new_hold_count = max(0, new_hold_count)
        new_sell_count = max(0, new_sell_count)
        
        # Calculate new consensus rating
        total_ratings = new_buy_count + new_hold_count + new_sell_count
        if total_ratings > 0:
            buy_percentage = (new_buy_count / total_ratings) * 100
            
            if buy_percentage >= 60:
                new_rating = "Strong Buy"
            elif buy_percentage >= 40:
                new_rating = "Buy"
            elif buy_percentage >= 20:
                new_rating = "Hold"
            else:
                new_rating = "Sell"
        else:
            new_rating = current_rating.analyst_rating or "Hold"
        
        # Create new rating entry for today (or update if exists)
        updated_rating, created = AnalystRating.objects.update_or_create(
            stock=stock,
            rating_date=today,
            defaults={
                'analyst_rating': new_rating,
                'buy_count': new_buy_count,
                'hold_count': new_hold_count,
                'sell_count': new_sell_count,
                'aggregate_rating': f"Updated based on {adjustment['positive_news_count']} positive news articles (sentiment: {adjustment['sentiment_score']:.2f})"
            }
        )
        
        action = "Created" if created else "Updated"
        message = f"{action} rating: {new_rating} (Buy: {new_buy_count}, Hold: {new_hold_count}, Sell: {new_sell_count}) based on {adjustment['positive_news_count']} positive news articles"
        
        logger.info(f"Updated analyst rating for {stock.symbol}: {message}")
        
        return True, message, updated_rating
        
    except Exception as e:
        logger.error(f"Error updating analyst rating for {stock.symbol}: {str(e)}")
        return False, f"Error: {str(e)}", None


def update_ratings_for_all_stocks_with_positive_news(days=7, min_positive_news=2):
    """
    Update analyst ratings for all stocks that have positive news
    
    Args:
        days: Number of days to look back for news
        min_positive_news: Minimum number of positive news articles required
    
    Returns:
        dict with summary statistics
    """
    cutoff_date = timezone.now() - timedelta(days=days)
    
    # Find stocks with positive news in the last N days
    stocks_with_positive_news = Stock.objects.filter(
        news__published_at__gte=cutoff_date,
        news__sentiment='positive'
    ).annotate(
        positive_news_count=models.Count('news', filter=models.Q(news__sentiment='positive', news__published_at__gte=cutoff_date))
    ).filter(
        positive_news_count__gte=min_positive_news
    ).distinct()
    
    results = {
        'total_stocks': stocks_with_positive_news.count(),
        'successful_updates': 0,
        'failed_updates': 0,
        'skipped': 0,
        'messages': []
    }
    
    for stock in stocks_with_positive_news:
        success, message, rating = update_analyst_rating_from_news(stock, days, min_positive_news)
        
        if success:
            results['successful_updates'] += 1
        elif "Insufficient" in message or "Need at least" in message:
            results['skipped'] += 1
        else:
            results['failed_updates'] += 1
        
        results['messages'].append({
            'stock': stock.symbol,
            'success': success,
            'message': message
        })
    
    return results

