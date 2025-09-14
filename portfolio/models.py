from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Stock(models.Model):
    symbol = models.CharField(max_length=10, unique=True)
    code = models.CharField(max_length=10)
    company_name = models.CharField(max_length=255)
    is_etf = models.BooleanField(default=False)
    tsx60_member = models.BooleanField(default=False)
    industry = models.CharField(max_length=100, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.symbol} - {self.company_name}"

class StockPrice(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='prices')
    price_date = models.DateField()
    last_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='CAD')
    volume = models.BigIntegerField(null=True, blank=True)
    fiftytwo_week_high = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fiftytwo_week_low = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ['stock', 'price_date']
        ordering = ['-price_date']

class Dividend(models.Model):
    FREQUENCY_CHOICES = [
        ('Monthly', 'Monthly'),
        ('Quarterly', 'Quarterly'),
        ('Semi-Annual', 'Semi-Annual'),
        ('Annual', 'Annual'),
        ('Unknown', 'Unknown'),
    ]
    
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='dividends')
    amount = models.DecimalField(max_digits=10, decimal_places=4)
    currency = models.CharField(max_length=3, default='CAD')
    yield_percent = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='Unknown')  
    declaration_date = models.DateField(null=True, blank=True)
    ex_dividend_date = models.DateField(null=True, blank=True)
    record_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['stock', 'ex_dividend_date']
        ordering = ['-ex_dividend_date']

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
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio')
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    shares_owned = models.PositiveIntegerField(default=0)
    average_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'stock']
        ordering = ['-created_at']

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
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alerts')
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    alert_source = models.CharField(max_length=10, choices=ALERT_SOURCES, default='both')
    threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    days_advance = models.IntegerField(default=1)  # For ex-date alerts
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol} - {self.alert_type}"

class Watchlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlists')
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'stock']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol}"

class DividendAlert(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dividend_alerts')
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    days_advance = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'stock']
    
    def __str__(self):
        return f"{self.user.username} - {self.stock.symbol} - Dividend Alert"