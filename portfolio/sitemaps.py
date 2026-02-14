"""
Sitemaps for SEO. Serves /sitemap.xml with static pages and stock detail URLs.
"""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Stock


class StaticViewSitemap(Sitemap):
    """Static pages (no URL kwargs)."""
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return [
            'home',
            'login',
            'register',
            'all_stocks',
            'dividend_calendar',
            'earnings_calendar',
            'drip_calculator',
            'canadian_tools',
            'big6_banks_dashboard',
            'contact_us',
            'donations',
            'privacy_policy',
            'terms_of_service',
            'newsletter_subscription',
            'posts_feed',
            'stock_notes',
            'transactions_list',
        ]

    def location(self, item):
        return reverse(item)


class StockSitemap(Sitemap):
    """Stock detail pages: /stocks/<symbol>/<slug>/ (SEO-friendly)"""
    changefreq = 'daily'
    priority = 0.7

    def items(self):
        return Stock.objects.filter(show_in_listing=True).order_by('symbol')

    def location(self, obj):
        return reverse('stock_detail', kwargs={'symbol': obj.symbol, 'slug': obj.get_seo_slug()})

    def lastmod(self, obj):
        return obj.updated_at
