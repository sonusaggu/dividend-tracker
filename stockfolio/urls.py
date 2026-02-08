from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include

from portfolio import error_handlers
from portfolio.sitemaps import StaticViewSitemap, StockSitemap

sitemaps = {
    'static': StaticViewSitemap,
    'stocks': StockSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps},
         name='django.contrib.sitemaps.views.sitemap'),
    path('', include('portfolio.urls')),
]

# Set custom error handlers
handler500 = error_handlers.handler500