"""
Sitemaps for SEO. Serves /sitemap.xml with static pages and stock detail URLs.

Priority guide:
  1.0  — home (most important)
  0.9  — main discovery pages (all stocks, dividend calendar)
  0.8  — supporting discovery pages (tools, community)
  0.7  — stock detail pages (high volume, daily content)
  0.5  — legal / info pages
"""
from datetime import date

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Stock


class StaticViewSitemap(Sitemap):
    """Public static pages — excluded: login, register, user-specific pages."""

    def items(self):
        # Tuples of (url_name, priority, changefreq)
        return [
            ('home',                   1.0, 'daily'),
            ('all_stocks',             0.9, 'daily'),
            ('dividend_calendar',      0.9, 'daily'),
            ('earnings_calendar',      0.8, 'weekly'),
            ('big6_banks_dashboard',   0.8, 'daily'),
            ('canadian_tools',         0.8, 'weekly'),
            ('posts_feed',             0.7, 'daily'),
            ('drip_calculator',        0.7, 'weekly'),
            ('contact_us',             0.5, 'monthly'),
            ('donations',              0.5, 'monthly'),
            ('privacy_policy',         0.3, 'yearly'),
            ('terms_of_service',       0.3, 'yearly'),
        ]

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]

    def changefreq(self, item):
        return item[2]

    def lastmod(self, item):
        # Static pages: return today so sitemaps are always fresh
        return date.today()


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
