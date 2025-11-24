from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Stock(models.Model):
    symbol = models.CharField(max_length=10, unique=True, db_index=True)
    code = models.CharField(max_length=10, db_index=True)
    company_name = models.CharField(max_length=255)
    is_etf = models.BooleanField(default=False)
    tsx60_member = models.BooleanField(default=False)
    industry = models.CharField(max_length=100, blank=True, db_index=True)
    sector = models.CharField(max_length=100, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['sector']),
            models.Index(fields=['symbol', 'sector']),
        ]

    def __str__(self):
        return f"{self.symbol} - {self.company_name}"

class StockPrice(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='prices', db_index=True)
    price_date = models.DateField(db_index=True)
    last_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='CAD')
    volume = models.BigIntegerField(null=True, blank=True)
    fiftytwo_week_high = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fiftytwo_week_low = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ['stock', 'price_date']
        ordering = ['-price_date']
        indexes = [
            models.Index(fields=['stock', '-price_date']),
            models.Index(fields=['-price_date']),
        ]

class Dividend(models.Model):
    FREQUENCY_CHOICES = [
        ('Monthly', 'Monthly'),
        ('Quarterly', 'Quarterly'),
        ('Semi-Annual', 'Semi-Annual'),
        ('Annual', 'Annual'),
        ('Unknown', 'Unknown'),
    ]
    
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='dividends', db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=4)
    currency = models.CharField(max_length=3, default='CAD')
    yield_percent = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='Unknown')  
    declaration_date = models.DateField(null=True, blank=True)
    ex_dividend_date = models.DateField(null=True, blank=True, db_index=True)
    record_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['stock', 'ex_dividend_date']
        ordering = ['-ex_dividend_date']
        indexes = [
            models.Index(fields=['stock', '-ex_dividend_date']),
            models.Index(fields=['ex_dividend_date']),
            models.Index(fields=['payment_date']),
        ]

    def __str__(self):
        return f"{self.stock.symbol} - ${self.amount} {self.frequency}"

class ValuationMetric(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='valuations')
    metric_date = models.DateField()
    pe_ratio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    eps = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    market_cap = models.CharField(max_length=20, blank=True)
    growth_3_year = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    growth_5_year = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ['stock', 'metric_date']
        ordering = ['-metric_date']

class AnalystRating(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='analyst_ratings')
    rating_date = models.DateField()
    aggregate_rating = models.TextField(blank=True)
    analyst_rating = models.CharField(max_length=10, blank=True)
    buy_count = models.IntegerField(null=True, blank=True)
    hold_count = models.IntegerField(null=True, blank=True)
    sell_count = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ['stock', 'rating_date']
        ordering = ['-rating_date']

class UserPortfolio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, db_index=True)
    shares_owned = models.PositiveIntegerField(default=0)
    average_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'stock']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'stock']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol}"

class UserAlert(models.Model):
    ALERT_TYPES = [
        ('ex_date', 'Ex-Dividend Date'),
        ('div_change', 'Dividend Change'),
        ('price_target', 'Price Target'),
        ('volume_spike', 'Volume Spike'),
    ]
    
    ALERT_SOURCES = [
        ('portfolio', 'Portfolio'),
        ('watchlist', 'Watchlist'),
        ('both', 'Both'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alerts', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, db_index=True)
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    alert_source = models.CharField(max_length=10, choices=ALERT_SOURCES, default='both')
    threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    days_advance = models.IntegerField(default=1)  # For ex-date alerts
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['user', 'alert_type']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol} - {self.alert_type}"

class Watchlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlists', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'stock']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'stock']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol}"

class DividendAlert(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dividend_alerts', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    days_advance = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'stock']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['is_active', 'days_advance']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol} - Dividend Alert"


class NewsletterSubscription(models.Model):
    FREQUENCY_CHOICES = [
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-Weekly'),
        ('monthly', 'Monthly'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='newsletter_subscription')
    is_active = models.BooleanField(default=True)
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default='weekly')
    subscribed_at = models.DateTimeField(auto_now_add=True)
    last_sent = models.DateTimeField(null=True, blank=True)
    preferences = models.JSONField(default=dict, blank=True)
    
    class Meta:
        verbose_name = "Newsletter Subscription"
        verbose_name_plural = "Newsletter Subscriptions"
    
    def __str__(self):
        return f"{self.user.username} - {self.frequency}"


class StockNews(models.Model):
    """News articles related to stocks"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='news', db_index=True)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    url = models.URLField(max_length=1000, unique=True, db_index=True)
    source = models.CharField(max_length=100, blank=True)
    author = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField(db_index=True)
    image_url = models.URLField(max_length=1000, blank=True)
    sentiment = models.CharField(max_length=20, blank=True)  # positive, negative, neutral
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['stock', '-published_at']),
            models.Index(fields=['-published_at']),
            models.Index(fields=['created_at']),  # For cleanup queries
            models.Index(fields=['stock', 'created_at']),  # Composite for stock-specific cleanup
        ]
        verbose_name = "Stock News"
        verbose_name_plural = "Stock News"
    
    def __str__(self):
        return f"{self.stock.symbol} - {self.title[:50]}"
    
    @classmethod
    def cleanup_old_news(cls, days=30, keep_per_stock=50):
        """
        Clean up old news articles
        Returns tuple: (deleted_count, kept_count)
        """
        from django.utils import timezone
        from datetime import timedelta
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Delete articles older than cutoff
        old_articles = cls.objects.filter(published_at__lt=cutoff_date)
        deleted_count = old_articles.count()
        old_articles.delete()
        
        # For each stock, keep only the most recent N articles
        from django.db.models import Count
        from portfolio.models import Stock
        
        stocks_with_excess = Stock.objects.annotate(
            news_count=Count('news')
        ).filter(news_count__gt=keep_per_stock)
        
        excess_deleted = 0
        for stock in stocks_with_excess:
            all_news = cls.objects.filter(stock=stock).order_by('-published_at')
            if all_news.count() > keep_per_stock:
                keep_ids = set(all_news[:keep_per_stock].values_list('id', flat=True))
                excess = all_news.exclude(id__in=keep_ids)
                excess_deleted += excess.count()
                excess.delete()
        
        total_deleted = deleted_count + excess_deleted
        remaining = cls.objects.count()
        
        return total_deleted, remaining


class PortfolioSnapshot(models.Model):
    """Track portfolio value over time for performance analysis"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio_snapshots', db_index=True)
    snapshot_date = models.DateField(db_index=True)
    total_value = models.DecimalField(max_digits=12, decimal_places=2)
    total_investment = models.DecimalField(max_digits=12, decimal_places=2)
    total_gain_loss = models.DecimalField(max_digits=12, decimal_places=2)
    total_roi_percent = models.DecimalField(max_digits=8, decimal_places=4)
    annual_dividend_income = models.DecimalField(max_digits=12, decimal_places=2)
    dividend_yield = models.DecimalField(max_digits=6, decimal_places=3)
    total_holdings = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'snapshot_date']
        ordering = ['-snapshot_date']
        indexes = [
            models.Index(fields=['user', '-snapshot_date']),
            models.Index(fields=['snapshot_date']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.snapshot_date} - ${self.total_value}"    