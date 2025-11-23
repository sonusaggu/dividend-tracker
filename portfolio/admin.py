from django.contrib import admin
from .models import (
    Stock, StockPrice, Dividend, ValuationMetric, AnalystRating,
    UserPortfolio, UserAlert, Watchlist, DividendAlert, NewsletterSubscription, StockNews
)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'code', 'company_name', 'sector', 'is_etf', 'tsx60_member', 'created_at')
    list_filter = ('is_etf', 'tsx60_member', 'sector', 'industry')
    search_fields = ('symbol', 'code', 'company_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(StockPrice)
class StockPriceAdmin(admin.ModelAdmin):
    list_display = ('stock', 'price_date', 'last_price', 'currency', 'volume')
    list_filter = ('currency', 'price_date')
    search_fields = ('stock__symbol', 'stock__company_name')
    date_hierarchy = 'price_date'
    readonly_fields = ('created_at',)


@admin.register(Dividend)
class DividendAdmin(admin.ModelAdmin):
    list_display = ('stock', 'amount', 'currency', 'yield_percent', 'frequency', 'ex_dividend_date', 'payment_date')
    list_filter = ('frequency', 'currency', 'ex_dividend_date')
    search_fields = ('stock__symbol', 'stock__company_name')
    date_hierarchy = 'ex_dividend_date'
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ValuationMetric)
class ValuationMetricAdmin(admin.ModelAdmin):
    list_display = ('stock', 'metric_date', 'pe_ratio', 'eps', 'market_cap')
    list_filter = ('metric_date',)
    search_fields = ('stock__symbol',)
    date_hierarchy = 'metric_date'
    readonly_fields = ('created_at',)


@admin.register(AnalystRating)
class AnalystRatingAdmin(admin.ModelAdmin):
    list_display = ('stock', 'rating_date', 'analyst_rating', 'buy_count', 'hold_count', 'sell_count')
    list_filter = ('analyst_rating', 'rating_date')
    search_fields = ('stock__symbol',)
    date_hierarchy = 'rating_date'
    readonly_fields = ('created_at',)


@admin.register(UserPortfolio)
class UserPortfolioAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock', 'shares_owned', 'average_cost', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'stock__symbol')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserAlert)
class UserAlertAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock', 'alert_type', 'alert_source', 'is_active', 'created_at')
    list_filter = ('alert_type', 'alert_source', 'is_active', 'created_at')
    search_fields = ('user__username', 'stock__symbol')
    readonly_fields = ('created_at',)


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'stock__symbol')
    readonly_fields = ('created_at',)


@admin.register(DividendAlert)
class DividendAlertAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock', 'is_active', 'days_advance', 'created_at', 'updated_at')
    list_filter = ('is_active', 'days_advance', 'created_at')
    search_fields = ('user__username', 'stock__symbol')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(NewsletterSubscription)
class NewsletterSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_active', 'frequency', 'subscribed_at', 'last_sent')
    list_filter = ('is_active', 'frequency', 'subscribed_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('subscribed_at',)


@admin.register(StockNews)
class StockNewsAdmin(admin.ModelAdmin):
    list_display = ('stock', 'title', 'source', 'published_at', 'sentiment', 'created_at')
    list_filter = ('source', 'sentiment', 'published_at', 'created_at')
    search_fields = ('stock__symbol', 'title', 'description')
    date_hierarchy = 'published_at'
    readonly_fields = ('created_at', 'updated_at')
    list_per_page = 50
