"""
Service layer for business logic separation
This module contains business logic that was previously in views
"""
from django.db.models import Subquery, OuterRef, Exists, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import (
    Stock, StockPrice, Dividend, UserPortfolio, 
    Watchlist, DividendAlert, ValuationMetric, AnalystRating
)


class PortfolioService:
    """Service for portfolio-related business logic"""
    
    FREQUENCY_MULTIPLIER = {
        'Monthly': 12,
        'Quarterly': 4,
        'Semi-Annual': 2,
        'Annual': 1,
    }
    
    @staticmethod
    def calculate_annual_dividend(dividend_amount, shares_owned, frequency):
        """Calculate annual dividend income"""
        if not dividend_amount or not shares_owned or not frequency:
            return 0
        multiplier = PortfolioService.FREQUENCY_MULTIPLIER.get(frequency, 0)
        return float(dividend_amount * shares_owned * multiplier)
    
    @staticmethod
    def get_portfolio_with_annotations(user):
        """Get portfolio items with optimized annotations"""
        return UserPortfolio.objects.filter(user=user).select_related('stock').annotate(
            latest_price_value=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('last_price')[:1]
            ),
            latest_price_date=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('price_date')[:1]
            ),
            latest_dividend_amount=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('amount')[:1]
            ),
            latest_dividend_yield=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('yield_percent')[:1]
            ),
            latest_dividend_frequency=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('frequency')[:1]
            ),
            latest_dividend_date=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('ex_dividend_date')[:1]
            ),
        )
    
    @staticmethod
    def get_watchlist_with_annotations(user):
        """Get watchlist items with optimized annotations"""
        return Watchlist.objects.filter(user=user).select_related('stock').annotate(
            latest_price_value=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('last_price')[:1]
            ),
            latest_price_date=Subquery(
                StockPrice.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-price_date').values('price_date')[:1]
            ),
            latest_dividend_amount=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('amount')[:1]
            ),
            latest_dividend_yield=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('yield_percent')[:1]
            ),
            latest_dividend_date=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('ex_dividend_date')[:1]
            ),
            latest_dividend_frequency=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('frequency')[:1]
            ),
        )


class StockService:
    """Service for stock-related business logic"""
    
    @staticmethod
    def get_stocks_with_annotations():
        """Get stocks with all required annotations for listing"""
        latest_dividends = Dividend.objects.filter(stock=OuterRef('pk')).order_by('-ex_dividend_date')
        upcoming_dividends = Dividend.objects.filter(
            stock=OuterRef('pk'),
            ex_dividend_date__gte=timezone.now().date()
        ).order_by('ex_dividend_date')
        latest_prices = StockPrice.objects.filter(stock=OuterRef('pk')).order_by('-price_date')
        
        return Stock.objects.all().annotate(
            latest_dividend_amount=Subquery(latest_dividends.values('amount')[:1]),
            latest_dividend_yield=Subquery(latest_dividends.values('yield_percent')[:1]),
            latest_dividend_date=Subquery(latest_dividends.values('ex_dividend_date')[:1]),
            latest_dividend_frequency=Subquery(latest_dividends.values('frequency')[:1]),
            upcoming_dividend_date=Subquery(upcoming_dividends.values('ex_dividend_date')[:1]),
            latest_price_value=Subquery(latest_prices.values('last_price')[:1]),
            latest_price_date=Subquery(latest_prices.values('price_date')[:1]),
            has_dividend=Exists(Dividend.objects.filter(stock=OuterRef('pk')))
        )
    
    @staticmethod
    def get_upcoming_dividends(days=30, limit=12):
        """Get upcoming dividends for the next N days"""
        today = timezone.now().date()
        end_date = today + timedelta(days=days)
        
        return Dividend.objects.filter(
            ex_dividend_date__gte=today,
            ex_dividend_date__lte=end_date
        ).select_related('stock').annotate(
            latest_price=Subquery(
                StockPrice.objects.filter(
                    stock=OuterRef('stock_id')
                ).order_by('-price_date').values('last_price')[:1]
            ),
            latest_price_date=Subquery(
                StockPrice.objects.filter(
                    stock=OuterRef('stock_id')
                ).order_by('-price_date').values('price_date')[:1]
            )
        ).order_by('ex_dividend_date')[:limit]


class AlertService:
    """Service for alert-related business logic"""
    
    MAX_DIVIDEND_ALERTS = 5
    MAX_WATCHLIST_ITEMS = 10
    
    @staticmethod
    def can_add_dividend_alert(user):
        """Check if user can add another dividend alert"""
        current_count = DividendAlert.objects.filter(user=user).count()
        return current_count < AlertService.MAX_DIVIDEND_ALERTS
    
    @staticmethod
    def can_add_watchlist_item(user):
        """Check if user can add another watchlist item"""
        current_count = Watchlist.objects.filter(user=user).count()
        return current_count < AlertService.MAX_WATCHLIST_ITEMS
    
    @staticmethod
    def get_alerts_with_annotations(user):
        """Get dividend alerts with optimized annotations"""
        return DividendAlert.objects.filter(user=user).select_related('stock').annotate(
            latest_dividend_amount=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('amount')[:1]
            ),
            latest_dividend_yield=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('yield_percent')[:1]
            ),
            latest_dividend_date=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('ex_dividend_date')[:1]
            ),
            latest_dividend_frequency=Subquery(
                Dividend.objects.filter(stock=OuterRef('stock_id'))
                .order_by('-ex_dividend_date').values('frequency')[:1]
            ),
        )

