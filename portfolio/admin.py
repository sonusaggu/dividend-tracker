from django.contrib import admin
from .models import (
    Stock, StockPrice, Dividend, ValuationMetric, AnalystRating,
    UserPortfolio, UserAlert, Watchlist, DividendAlert, NewsletterSubscription, StockNews,
    AffiliateLink, SponsoredContent, UserProfile, Follow, Post, Comment, PostLike, CommentLike,
    StockNote, Transaction, WebsiteMetric, UserSession
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


@admin.register(AffiliateLink)
class AffiliateLinkAdmin(admin.ModelAdmin):
    list_display = ('name', 'platform_type', 'is_active', 'display_order', 'click_count', 'created_at')
    list_filter = ('platform_type', 'is_active', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('click_count', 'created_at', 'updated_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'platform_type', 'description', 'logo_url')
        }),
        ('Affiliate Details', {
            'fields': ('affiliate_url', 'bonus_offer')
        }),
        ('Display Settings', {
            'fields': ('is_active', 'display_order')
        }),
        ('Statistics', {
            'fields': ('click_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SponsoredContent)
class SponsoredContentAdmin(admin.ModelAdmin):
    list_display = ('title', 'content_type', 'stock', 'is_active', 'display_order', 'view_count', 'click_count', 'created_at')
    list_filter = ('content_type', 'is_active', 'start_date', 'end_date', 'created_at')
    search_fields = ('title', 'description', 'stock__symbol')
    readonly_fields = ('view_count', 'click_count', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Content Information', {
            'fields': ('title', 'content_type', 'description', 'image_url', 'stock')
        }),
        ('Link Settings', {
            'fields': ('link_url', 'link_text')
        }),
        ('Display Settings', {
            'fields': ('is_active', 'display_order', 'start_date', 'end_date')
        }),
        ('Statistics', {
            'fields': ('view_count', 'click_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'location', 'created_at', 'updated_at')
    search_fields = ('user__username', 'user__email', 'bio', 'location')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Profile Details', {
            'fields': ('bio', 'avatar', 'location', 'website', 'twitter_handle')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ('follower', 'following', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('follower__username', 'following__username')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('user', 'post_type', 'title', 'stock', 'likes_count', 'comments_count', 'views_count', 'created_at')
    list_filter = ('post_type', 'is_pinned', 'is_edited', 'created_at')
    search_fields = ('user__username', 'title', 'content', 'stock__symbol')
    readonly_fields = ('likes_count', 'comments_count', 'views_count', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Post Information', {
            'fields': ('user', 'post_type', 'title', 'content', 'stock')
        }),
        ('Engagement', {
            'fields': ('likes_count', 'comments_count', 'views_count')
        }),
        ('Moderation', {
            'fields': ('is_pinned', 'is_edited')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'post', 'likes_count', 'is_edited', 'created_at')
    list_filter = ('is_edited', 'created_at')
    search_fields = ('user__username', 'content', 'post__title')
    readonly_fields = ('likes_count', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'post', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'post__title')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'


@admin.register(CommentLike)
class CommentLikeAdmin(admin.ModelAdmin):
    list_display = ('user', 'comment', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'comment__content')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'


@admin.register(StockNote)
class StockNoteAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock', 'note_type', 'title', 'is_private', 'created_at', 'updated_at')
    list_filter = ('note_type', 'is_private', 'created_at')
    search_fields = ('user__username', 'stock__symbol', 'title', 'content', 'tags')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Note Information', {
            'fields': ('user', 'stock', 'note_type', 'title', 'content', 'tags', 'is_private')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock', 'transaction_type', 'transaction_date', 'shares', 'price_per_share', 'total_amount', 'realized_gain_loss', 'created_at')
    list_filter = ('transaction_type', 'cost_basis_method', 'transaction_date', 'is_processed')
    search_fields = ('user__username', 'stock__symbol', 'stock__company_name', 'notes')
    date_hierarchy = 'transaction_date'
    readonly_fields = ('created_at', 'updated_at', 'total_amount')
    fieldsets = (
        ('Transaction Information', {
            'fields': ('user', 'stock', 'transaction_type', 'transaction_date', 'shares', 'price_per_share', 'fees', 'total_amount')
        }),
        ('Cost Basis & Gains', {
            'fields': ('cost_basis_method', 'realized_gain_loss', 'is_processed')
        }),
        ('Additional Information', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(WebsiteMetric)
class WebsiteMetricAdmin(admin.ModelAdmin):
    list_display = ('user', 'path', 'method', 'status_code', 'is_authenticated', 'is_mobile', 'is_bot', 'timestamp', 'response_time_ms')
    list_filter = ('method', 'status_code', 'is_authenticated', 'is_mobile', 'is_bot', 'timestamp')
    search_fields = ('path', 'user__username', 'ip_address', 'user_agent')
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp', 'response_time_ms')
    list_per_page = 100
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user')


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'session_key', 'ip_address', 'started_at', 'last_activity', 'page_views', 'is_active', 'duration_display')
    list_filter = ('is_active', 'started_at', 'last_activity')
    search_fields = ('user__username', 'session_key', 'ip_address')
    date_hierarchy = 'started_at'
    readonly_fields = ('started_at', 'last_activity', 'duration_seconds')
    
    def duration_display(self, obj):
        """Display duration in human-readable format"""
        seconds = obj.duration_seconds
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    duration_display.short_description = 'Duration'
