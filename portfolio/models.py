import re
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session

class Stock(models.Model):
    symbol = models.CharField(max_length=10, unique=True, db_index=True)
    code = models.CharField(max_length=10, db_index=True)
    company_name = models.CharField(max_length=255)
    is_etf = models.BooleanField(default=False)
    tsx60_member = models.BooleanField(default=False)
    industry = models.CharField(max_length=100, blank=True, db_index=True)
    sector = models.CharField(max_length=100, blank=True, db_index=True)
    show_in_listing = models.BooleanField(default=True, db_index=True, help_text="If False, stock won't appear in all stocks page")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['sector']),
            models.Index(fields=['symbol', 'sector']),
        ]

    def __str__(self):
        return f"{self.symbol} - {self.company_name}"

    def get_seo_slug(self):
        """SEO-friendly URL slug from company name (lowercase, hyphens, no special chars). Never returns empty."""
        if not self.company_name:
            return (self.symbol or 'symbol').lower()
        # Normalize: lowercase, keep alphanumeric/spaces/hyphens, collapse spaces and hyphens
        s = re.sub(r'[^a-z0-9\s-]', '', self.company_name.lower())
        s = re.sub(r'[\s-]+', '-', s).strip('-')
        return (s or (self.symbol or 'symbol')).lower()

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

class Earnings(models.Model):
    """Store earnings calendar and earnings data"""
    TIME_CHOICES = [
        ('bmo', 'Before Market Open'),
        ('amc', 'After Market Close'),
        ('dmh', 'During Market Hours'),
        ('', 'Not Specified'),
    ]
    
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='earnings', db_index=True)
    earnings_date = models.DateField(db_index=True)
    time = models.CharField(max_length=10, choices=TIME_CHOICES, blank=True)
    eps_estimate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    eps_actual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    revenue_estimate = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    revenue_actual = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=50, blank=True)  # 'finnhub', 'alphavantage', 'fmp', etc.
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['stock', 'earnings_date']
        ordering = ['-earnings_date']
        indexes = [
            models.Index(fields=['stock', '-earnings_date']),
            models.Index(fields=['earnings_date']),
        ]

    def __str__(self):
        return f"{self.stock.symbol} - Earnings on {self.earnings_date}"
    
    @property
    def eps_surprise(self):
        """Calculate EPS surprise percentage"""
        if self.eps_estimate and self.eps_actual:
            if float(self.eps_estimate) != 0:
                return ((float(self.eps_actual) - float(self.eps_estimate)) / abs(float(self.eps_estimate))) * 100
        return None
    
    @property
    def revenue_surprise(self):
        """Calculate revenue surprise percentage"""
        if self.revenue_estimate and self.revenue_actual:
            if float(self.revenue_estimate) != 0:
                return ((float(self.revenue_actual) - float(self.revenue_estimate)) / abs(float(self.revenue_estimate))) * 100
        return None

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

class Transaction(models.Model):
    """Track buy/sell transactions for cost basis calculation"""
    TRANSACTION_TYPES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
        ('DIVIDEND', 'Dividend Reinvestment'),
        ('SPLIT', 'Stock Split'),
        ('MERGER', 'Merger/Acquisition'),
    ]
    
    COST_BASIS_METHODS = [
        ('FIFO', 'First In First Out'),
        ('LIFO', 'Last In First Out'),
        ('AVERAGE', 'Average Cost'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='transactions', db_index=True)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, db_index=True)
    transaction_date = models.DateField(db_index=True)
    shares = models.DecimalField(max_digits=12, decimal_places=6)
    price_per_share = models.DecimalField(max_digits=10, decimal_places=4)
    fees = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)
    # For sell transactions, track which buy transactions were used (for FIFO/LIFO)
    cost_basis_method = models.CharField(max_length=10, choices=COST_BASIS_METHODS, default='FIFO')
    realized_gain_loss = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Track if this transaction has been used in cost basis calculation
    is_processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'stock', '-transaction_date']),
            models.Index(fields=['user', '-transaction_date']),
            models.Index(fields=['transaction_type', 'transaction_date']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.transaction_type} {self.shares} {self.stock.symbol} @ ${self.price_per_share} on {self.transaction_date}"
    
    def save(self, *args, **kwargs):
        # Calculate total amount
        if not self.total_amount:
            self.total_amount = (self.shares * self.price_per_share) + self.fees
        super().save(*args, **kwargs)
    
    @property
    def net_amount(self):
        """Net amount after fees"""
        return self.total_amount - self.fees
    
    def calculate_realized_gain_loss(self, cost_basis):
        """Calculate realized gain/loss for sell transactions"""
        if self.transaction_type == 'SELL':
            from decimal import Decimal
            # Convert all values to Decimal for precise calculation
            shares_decimal = Decimal(str(self.shares))
            price_decimal = Decimal(str(self.price_per_share))
            fees_decimal = Decimal(str(self.fees))
            cost_basis_decimal = Decimal(str(cost_basis)) if cost_basis is not None else Decimal('0')
            
            # Calculate proceeds: (shares * price) - fees
            proceeds = (shares_decimal * price_decimal) - fees_decimal
            
            # Calculate gain/loss: proceeds - cost_basis
            gain_loss = proceeds - cost_basis_decimal
            
            # Convert to Decimal field format
            self.realized_gain_loss = gain_loss
            return float(gain_loss)
        return None

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

class WatchlistGroup(models.Model):
    """Groups/categories for organizing watchlist items"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlist_groups', db_index=True)
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default='#3B82F6', help_text='Hex color code for the group')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    order = models.IntegerField(default=0, help_text='Order for displaying groups')
    
    class Meta:
        unique_together = ['user', 'name']
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['user', 'order']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.name}"


class Watchlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlists', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, db_index=True)
    group = models.ForeignKey(WatchlistGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='watchlist_items', db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'stock']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'stock']),
            models.Index(fields=['user', 'group']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol}"


class StockTag(models.Model):
    """User-defined tags for organizing stocks"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stock_tags', db_index=True)
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default='#6B7280', help_text='Hex color code for the tag')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'name']
        ordering = ['name']
        indexes = [
            models.Index(fields=['user', 'name']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.name}"


class TaggedStock(models.Model):
    """Many-to-many relationship between stocks and tags"""
    tag = models.ForeignKey(StockTag, on_delete=models.CASCADE, related_name='tagged_stocks', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='tags', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['tag', 'stock']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tag', 'stock']),
            models.Index(fields=['stock']),
        ]
    
    def __str__(self):
        return f"{self.tag.name} - {self.stock.symbol}"

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


class EmailVerification(models.Model):
    """Email verification tokens for user account activation"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification', db_index=True)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['user', 'is_verified']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {'Verified' if self.is_verified else 'Pending'}"
    
    def is_expired(self):
        """Check if verification token is expired (24 hours)"""
        from datetime import timedelta
        if self.is_verified:
            return False
        expiry_time = self.created_at + timedelta(hours=24)
        return timezone.now() > expiry_time


class ScrapeStatus(models.Model):
    """Track daily scrape status and results"""
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running', db_index=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    days = models.IntegerField(default=60, help_text='Number of days of historical data to fetch')
    
    # Results
    total_stocks = models.IntegerField(default=0, help_text='Total stocks processed')
    success_count = models.IntegerField(default=0, help_text='Successfully updated stocks')
    failed_count = models.IntegerField(default=0, help_text='Failed stocks')
    
    # Error tracking
    error_message = models.TextField(blank=True, null=True, help_text='Error message if failed')
    failed_symbols = models.JSONField(default=list, blank=True, help_text='List of failed stock symbols')
    
    # Additional info
    duration_seconds = models.IntegerField(null=True, blank=True, help_text='Duration in seconds')
    notes = models.TextField(blank=True, help_text='Additional notes or details')
    
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['status', '-started_at']),
        ]
        verbose_name = 'Scrape Status'
        verbose_name_plural = 'Scrape Statuses'
    
    def __str__(self):
        return f"Scrape {self.id} - {self.status} ({self.started_at.strftime('%Y-%m-%d %H:%M:%S')})"
    
    @property
    def is_running(self):
        """Check if scrape is currently running"""
        return self.status == 'running'
    
    @property
    def success_rate(self):
        """Calculate success rate percentage"""
        if self.total_stocks == 0:
            return 0.0
        return round((self.success_count / self.total_stocks) * 100, 2)
    
    @property
    def duration_minutes(self):
        """Get duration in minutes"""
        if self.duration_seconds:
            return round(self.duration_seconds / 60, 1)
        return None
    
    def mark_completed(self, success_count, failed_count, total_stocks, failed_symbols=None, notes=''):
        """Mark scrape as completed"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.success_count = success_count
        self.failed_count = failed_count
        self.total_stocks = total_stocks
        if failed_symbols:
            self.failed_symbols = failed_symbols[:50]  # Limit to 50 symbols
        self.notes = notes
        
        # Calculate duration
        if self.started_at:
            duration = (self.completed_at - self.started_at).total_seconds()
            self.duration_seconds = int(duration)
        
        self.save()
    
    def mark_failed(self, error_message, notes=''):
        """Mark scrape as failed"""
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.notes = notes
        
        # Calculate duration
        if self.started_at:
            duration = (self.completed_at - self.started_at).total_seconds()
            self.duration_seconds = int(duration)
        
        self.save()
    
    @classmethod
    def get_latest(cls):
        """Get the latest scrape status"""
        return cls.objects.first()
    
    @classmethod
    def get_running(cls):
        """Get currently running scrape if any"""
        return cls.objects.filter(status='running').first()
    
    @classmethod
    def create_new(cls, days=60):
        """Create a new scrape status record"""
        # Mark any existing running scrapes as cancelled
        cls.objects.filter(status='running').update(status='cancelled', completed_at=timezone.now())
        
        # Create new status
        return cls.objects.create(
            status='running',
            days=days,
            started_at=timezone.now()
        )


class AffiliateLink(models.Model):
    """Affiliate links for brokers and financial services"""
    PLATFORM_CHOICES = [
        ('broker', 'Broker'),
        ('platform', 'Trading Platform'),
        ('service', 'Financial Service'),
        ('other', 'Other'),
    ]
    
    name = models.CharField(max_length=200, help_text="Name of the broker/service")
    platform_type = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='broker')
    affiliate_url = models.URLField(help_text="Affiliate/referral link")
    description = models.TextField(blank=True, help_text="Short description")
    logo_url = models.URLField(blank=True, help_text="URL to logo image")
    bonus_offer = models.CharField(max_length=200, blank=True, help_text="e.g., 'Free $50 when you sign up'")
    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.IntegerField(default=0, help_text="Order for display (lower = first)")
    click_count = models.IntegerField(default=0, help_text="Total clicks tracked")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = "Affiliate Link"
        verbose_name_plural = "Affiliate Links"
        indexes = [
            models.Index(fields=['is_active', 'display_order']),
            models.Index(fields=['platform_type']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.platform_type})"
    
    def track_click(self):
        """Increment click counter"""
        self.click_count += 1
        self.save(update_fields=['click_count'])


class UserProfile(models.Model):
    """Extended user profile with social features"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(max_length=500, blank=True, help_text="Short bio about yourself")
    avatar = models.URLField(blank=True, help_text="URL to profile picture")
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    twitter_handle = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
    
    def __str__(self):
        return f"{self.user.username}'s Profile"
    
    @property
    def followers_count(self):
        """Get number of followers"""
        return self.user.followers.count()
    
    @property
    def following_count(self):
        """Get number of users being followed"""
        return self.user.following.count()
    
    @property
    def posts_count(self):
        """Get number of posts"""
        return self.user.posts.count()


class Follow(models.Model):
    """Follow relationship between users"""
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following', db_index=True)
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followers', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['follower', 'following']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['follower', 'following']),
            models.Index(fields=['following']),
        ]
        verbose_name = "Follow"
        verbose_name_plural = "Follows"
    
    def __str__(self):
        return f"{self.follower.username} follows {self.following.username}"


class Post(models.Model):
    """User posts/insights about stocks or investing"""
    POST_TYPE_CHOICES = [
        ('insight', 'Investment Insight'),
        ('analysis', 'Stock Analysis'),
        ('question', 'Question'),
        ('discussion', 'Discussion'),
        ('update', 'Portfolio Update'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts', db_index=True)
    post_type = models.CharField(max_length=20, choices=POST_TYPE_CHOICES, default='insight')
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField(max_length=5000, help_text="Post content")
    
    # Optional stock reference
    stock = models.ForeignKey(Stock, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts')
    
    # Engagement metrics
    likes_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    views_count = models.IntegerField(default=0)
    
    # Moderation
    is_pinned = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_pinned', '-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['stock', '-created_at']),
            models.Index(fields=['post_type', '-created_at']),
        ]
        verbose_name = "Post"
        verbose_name_plural = "Posts"
    
    def __str__(self):
        return f"{self.user.username} - {self.post_type} ({self.created_at.date()})"
    
    def increment_views(self):
        """Increment view counter"""
        self.views_count += 1
        self.save(update_fields=['views_count'])


class Comment(models.Model):
    """Comments on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments', db_index=True)
    content = models.TextField(max_length=2000)
    likes_count = models.IntegerField(default=0)
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
        verbose_name = "Comment"
        verbose_name_plural = "Comments"
    
    def __str__(self):
        return f"{self.user.username} on {self.post.id}"


class PostLike(models.Model):
    """Likes on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='post_likes', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_likes', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']
        indexes = [
            models.Index(fields=['post', 'user']),
        ]
        verbose_name = "Post Like"
        verbose_name_plural = "Post Likes"
    
    def __str__(self):
        return f"{self.user.username} likes {self.post.id}"
    
    def save(self, *args, **kwargs):
        """Update post likes count when saving"""
        super().save(*args, **kwargs)
        self.post.likes_count = self.post.post_likes.count()
        self.post.save(update_fields=['likes_count'])
    
    def delete(self, *args, **kwargs):
        """Update post likes count when deleting"""
        post = self.post
        super().delete(*args, **kwargs)
        post.likes_count = post.post_likes.count()
        post.save(update_fields=['likes_count'])


class CommentLike(models.Model):
    """Likes on comments"""
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='comment_likes', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comment_likes', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['comment', 'user']
        indexes = [
            models.Index(fields=['comment', 'user']),
        ]
        verbose_name = "Comment Like"
        verbose_name_plural = "Comment Likes"
    
    def __str__(self):
        return f"{self.user.username} likes comment {self.comment.id}"
    
    def save(self, *args, **kwargs):
        """Update comment likes count when saving"""
        super().save(*args, **kwargs)
        self.comment.likes_count = self.comment.comment_likes.count()
        self.comment.save(update_fields=['likes_count'])
    
    def delete(self, *args, **kwargs):
        """Update comment likes count when deleting"""
        comment = self.comment
        super().delete(*args, **kwargs)
        comment.likes_count = comment.comment_likes.count()
        comment.save(update_fields=['likes_count'])


class SponsoredContent(models.Model):
    """Sponsored content - featured stocks, educational content, etc."""
    CONTENT_TYPE_CHOICES = [
        ('featured_stock', 'Featured Stock'),
        ('educational', 'Educational Content'),
        ('promotion', 'Promotion'),
        ('advertisement', 'Advertisement'),
    ]
    
    title = models.CharField(max_length=200)
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES, default='featured_stock')
    description = models.TextField(help_text="Content description or body")
    image_url = models.URLField(blank=True, help_text="URL to featured image")
    link_url = models.URLField(blank=True, help_text="Optional link URL")
    link_text = models.CharField(max_length=100, blank=True, help_text="Text for the link button")
    
    # For featured stocks
    stock = models.ForeignKey(Stock, on_delete=models.SET_NULL, null=True, blank=True, 
                              help_text="If content type is 'featured_stock', select a stock")
    
    # Display settings
    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.IntegerField(default=0, help_text="Order for display (lower = first)")
    start_date = models.DateTimeField(null=True, blank=True, help_text="When to start showing")
    end_date = models.DateTimeField(null=True, blank=True, help_text="When to stop showing")
    
    # Tracking
    view_count = models.IntegerField(default=0)
    click_count = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['display_order', '-created_at']
        verbose_name = "Sponsored Content"
        verbose_name_plural = "Sponsored Content"
        indexes = [
            models.Index(fields=['is_active', 'display_order']),
            models.Index(fields=['content_type']),
            models.Index(fields=['start_date', 'end_date']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.get_content_type_display()})"
    
    def is_currently_active(self):
        """Check if content should be displayed based on dates"""
        if not self.is_active:
            return False
        now = timezone.now()
        if self.start_date and now < self.start_date:
            return False
        if self.end_date and now > self.end_date:
            return False
        return True
    
    def track_view(self):
        """Increment view counter"""
        self.view_count += 1
        self.save(update_fields=['view_count'])
    
    def track_click(self):
        """Increment click counter"""
        self.click_count += 1
        self.save(update_fields=['click_count'])


class UserProfile(models.Model):
    """Extended user profile with social features"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(max_length=500, blank=True, help_text="Short bio about yourself")
    avatar = models.URLField(blank=True, help_text="URL to profile picture")
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    twitter_handle = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
    
    def __str__(self):
        return f"{self.user.username}'s Profile"
    
    @property
    def followers_count(self):
        """Get number of followers"""
        return self.user.followers.count()
    
    @property
    def following_count(self):
        """Get number of users being followed"""
        return self.user.following.count()
    
    @property
    def posts_count(self):
        """Get number of posts"""
        return self.user.posts.count()


class Follow(models.Model):
    """Follow relationship between users"""
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following', db_index=True)
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followers', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['follower', 'following']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['follower', 'following']),
            models.Index(fields=['following']),
        ]
        verbose_name = "Follow"
        verbose_name_plural = "Follows"
    
    def __str__(self):
        return f"{self.follower.username} follows {self.following.username}"


class Post(models.Model):
    """User posts/insights about stocks or investing"""
    POST_TYPE_CHOICES = [
        ('insight', 'Investment Insight'),
        ('analysis', 'Stock Analysis'),
        ('question', 'Question'),
        ('discussion', 'Discussion'),
        ('update', 'Portfolio Update'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts', db_index=True)
    post_type = models.CharField(max_length=20, choices=POST_TYPE_CHOICES, default='insight')
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField(max_length=5000, help_text="Post content")
    
    # Optional stock reference
    stock = models.ForeignKey(Stock, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts')
    
    # Engagement metrics
    likes_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    views_count = models.IntegerField(default=0)
    
    # Moderation
    is_pinned = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_pinned', '-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['stock', '-created_at']),
            models.Index(fields=['post_type', '-created_at']),
        ]
        verbose_name = "Post"
        verbose_name_plural = "Posts"
    
    def __str__(self):
        return f"{self.user.username} - {self.post_type} ({self.created_at.date()})"
    
    def increment_views(self):
        """Increment view counter"""
        self.views_count += 1
        self.save(update_fields=['views_count'])


class Comment(models.Model):
    """Comments on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments', db_index=True)
    content = models.TextField(max_length=2000)
    likes_count = models.IntegerField(default=0)
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
        verbose_name = "Comment"
        verbose_name_plural = "Comments"
    
    def __str__(self):
        return f"{self.user.username} on {self.post.id}"


class PostLike(models.Model):
    """Likes on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='post_likes', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_likes', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']
        indexes = [
            models.Index(fields=['post', 'user']),
        ]
        verbose_name = "Post Like"
        verbose_name_plural = "Post Likes"
    
    def __str__(self):
        return f"{self.user.username} likes {self.post.id}"
    
    def save(self, *args, **kwargs):
        """Update post likes count when saving"""
        super().save(*args, **kwargs)
        self.post.likes_count = self.post.post_likes.count()
        self.post.save(update_fields=['likes_count'])
    
    def delete(self, *args, **kwargs):
        """Update post likes count when deleting"""
        post = self.post
        super().delete(*args, **kwargs)
        post.likes_count = post.post_likes.count()
        post.save(update_fields=['likes_count'])


class CommentLike(models.Model):
    """Likes on comments"""
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='comment_likes', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comment_likes', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['comment', 'user']
        indexes = [
            models.Index(fields=['comment', 'user']),
        ]
        verbose_name = "Comment Like"
        verbose_name_plural = "Comment Likes"
    
    def __str__(self):
        return f"{self.user.username} likes comment {self.comment.id}"
    
    def save(self, *args, **kwargs):
        """Update comment likes count when saving"""
        super().save(*args, **kwargs)
        self.comment.likes_count = self.comment.comment_likes.count()
        self.comment.save(update_fields=['likes_count'])
    
    def delete(self, *args, **kwargs):
        """Update comment likes count when deleting"""
        comment = self.comment
        super().delete(*args, **kwargs)
        comment.likes_count = comment.comment_likes.count()
        comment.save(update_fields=['likes_count'])


class StockNote(models.Model):
    """User notes and journal entries for stocks"""
    NOTE_TYPE_CHOICES = [
        ('note', 'Quick Note'),
        ('research', 'Research'),
        ('journal', 'Journal Entry'),
        ('buy', 'Buy Decision'),
        ('sell', 'Sell Decision'),
        ('watch', 'Watch'),
        ('analysis', 'Analysis'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stock_notes', db_index=True)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='notes', db_index=True)
    note_type = models.CharField(max_length=20, choices=NOTE_TYPE_CHOICES, default='note', db_index=True)
    title = models.CharField(max_length=200, blank=True, help_text="Optional title for the note")
    content = models.TextField(help_text="Note content")
    tags = models.CharField(max_length=200, blank=True, help_text="Comma-separated tags (buy, sell, research, etc.)")
    is_private = models.BooleanField(default=True, help_text="Private notes are only visible to you")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['stock', '-created_at']),
            models.Index(fields=['user', 'stock', '-created_at']),
            models.Index(fields=['note_type', '-created_at']),
        ]
        verbose_name = "Stock Note"
        verbose_name_plural = "Stock Notes"
    
    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol} - {self.note_type} ({self.created_at.date()})"
    
    def get_tags_list(self):
        """Return tags as a list"""
        if self.tags:
            return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
        return []
    
    def set_tags_list(self, tags_list):
        """Set tags from a list"""
        self.tags = ', '.join([tag.strip() for tag in tags_list if tag.strip()])
    
    @property
    def preview(self):
        """Get a preview of the note content"""
        if len(self.content) > 150:
            return self.content[:150] + '...'
        return self.content


class WebsiteMetric(models.Model):
    """Track website metrics for analytics"""
    # User information
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='website_metrics', db_index=True)
    session_key = models.CharField(max_length=40, blank=True, default='', db_index=True)  # Django session key (empty string if no session)
    
    # Request information
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.TextField(blank=True)
    referrer = models.URLField(max_length=500, blank=True)
    
    # Page information
    path = models.CharField(max_length=500, db_index=True)
    method = models.CharField(max_length=10, default='GET')
    status_code = models.IntegerField(default=200, db_index=True)
    
    # Timing information
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    response_time_ms = models.IntegerField(null=True, blank=True)  # Response time in milliseconds
    
    # Additional metadata
    is_authenticated = models.BooleanField(default=False, db_index=True)
    is_mobile = models.BooleanField(default=False, db_index=True)
    is_bot = models.BooleanField(default=False, db_index=True)
    country = models.CharField(max_length=2, blank=True, db_index=True)  # ISO country code
    city = models.CharField(max_length=100, blank=True, db_index=True)
    region = models.CharField(max_length=100, blank=True)  # State/Province
    timezone = models.CharField(max_length=50, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['path', '-timestamp']),
            models.Index(fields=['session_key', '-timestamp']),
            models.Index(fields=['is_authenticated', '-timestamp']),
            models.Index(fields=['timestamp']),  # For date range queries
        ]
        verbose_name = "Website Metric"
        verbose_name_plural = "Website Metrics"
    
    def __str__(self):
        user_str = self.user.username if self.user else 'Anonymous'
        return f"{user_str} - {self.path} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
    
    @classmethod
    def get_visitor_count(cls, start_date=None, end_date=None):
        """Get unique visitor count for a date range"""
        queryset = cls.objects.all()
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        
        # Count unique sessions and authenticated users
        unique_sessions = queryset.exclude(session_key='').values('session_key').distinct().count()
        unique_users = queryset.exclude(user=None).values('user').distinct().count()
        
        return {
            'total_visitors': unique_sessions + unique_users,
            'anonymous_visitors': unique_sessions,
            'authenticated_visitors': unique_users,
        }
    
    @classmethod
    def get_page_views(cls, start_date=None, end_date=None):
        """Get total page views for a date range"""
        queryset = cls.objects.all()
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        return queryset.count()
    
    @classmethod
    def get_top_pages(cls, start_date=None, end_date=None, limit=10):
        """Get top pages by view count"""
        queryset = cls.objects.all()
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        
        from django.db.models import Count
        return queryset.values('path').annotate(
            view_count=Count('id')
        ).order_by('-view_count')[:limit]


class UserSession(models.Model):
    """Track user sessions for analytics"""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sessions', db_index=True)
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Session timing
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_activity = models.DateTimeField(default=timezone.now, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    # Session metrics
    page_views = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    
    # Additional info
    referrer = models.URLField(max_length=500, blank=True)
    country = models.CharField(max_length=2, blank=True)
    
    class Meta:
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['user', '-last_activity']),
            models.Index(fields=['session_key']),
            models.Index(fields=['is_active', '-last_activity']),
        ]
        verbose_name = "User Session"
        verbose_name_plural = "User Sessions"
    
    def __str__(self):
        user_str = self.user.username if self.user else 'Anonymous'
        return f"{user_str} - {self.started_at.strftime('%Y-%m-%d %H:%M')}"
    
    @property
    def duration_seconds(self):
        """Calculate session duration in seconds"""
        end_time = self.ended_at or timezone.now()
        return int((end_time - self.started_at).total_seconds())