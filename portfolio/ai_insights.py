"""
Free AI-style insights using only database data.
No external APIs, no paid services — everything runs on your existing data.
"""
from django.utils import timezone
from datetime import timedelta

from .models import (
    Stock,
    StockPrice,
    Dividend,
    ValuationMetric,
    Earnings,
    StockNews,
)
from .services import PortfolioService


def get_portfolio_insights(user):
    """
    Generate portfolio insights from DB only (diversification, concentration, dividends, performance).
    Returns list of dicts: {'type': str, 'title': str, 'message': str, 'icon': str}
    """
    insights = []
    try:
        portfolio_items = PortfolioService.get_portfolio_with_annotations(user)
        if not portfolio_items:
            insights.append({
                'type': 'empty',
                'title': 'Start building',
                'message': 'Add stocks to your portfolio to get personalized insights and track performance.',
                'icon': 'sparkles',
            })
            return insights

        total_value = 0
        sector_values = {}
        annual_dividends = 0
        for item in portfolio_items:
            if item.latest_price_value and item.shares_owned:
                val = float(item.latest_price_value * item.shares_owned)
                total_value += val
                if item.stock.sector:
                    sector_values[item.stock.sector] = sector_values.get(item.stock.sector, 0) + val
            annual_dividends += PortfolioService.calculate_annual_dividend(
                item.latest_dividend_amount,
                item.shares_owned,
                item.latest_dividend_frequency,
            )

        # Diversification
        num_sectors = len(sector_values)
        if num_sectors >= 4:
            insights.append({
                'type': 'diversification',
                'title': 'Well diversified',
                'message': f'Your portfolio spans {num_sectors} sectors. This can help reduce sector-specific risk.',
                'icon': 'check',
            })
        elif num_sectors >= 1 and total_value > 0:
            top_sector_pct = max(sector_values.values()) / total_value * 100
            if top_sector_pct > 50:
                insights.append({
                    'type': 'concentration',
                    'title': 'Sector concentration',
                    'message': f'Over half of your portfolio is in one sector. Consider adding other sectors to spread risk.',
                    'icon': 'info',
                })
            elif num_sectors == 1:
                insights.append({
                    'type': 'diversification',
                    'title': 'Single sector',
                    'message': 'All holdings are in one sector. Adding other sectors may improve diversification.',
                    'icon': 'info',
                })

        # Dividend summary
        if total_value > 0 and annual_dividends > 0:
            yield_pct = (annual_dividends / total_value) * 100
            if yield_pct >= 4:
                insights.append({
                    'type': 'dividend',
                    'title': 'Strong dividend income',
                    'message': f'Portfolio yield is {yield_pct:.1f}%. You\'re earning ${annual_dividends:,.0f}/year from dividends.',
                    'icon': 'trending_up',
                })
            else:
                insights.append({
                    'type': 'dividend',
                    'title': 'Dividend income',
                    'message': f'Estimated annual dividends: ${annual_dividends:,.0f} ({yield_pct:.1f}% yield).',
                    'icon': 'cash',
                })

        # Total holdings
        count = portfolio_items.count()
        if count <= 2 and total_value > 0:
            insights.append({
                'type': 'holdings',
                'title': 'Few holdings',
                'message': f'You have {count} holding(s). Adding more stocks can diversify company-specific risk.',
                'icon': 'info',
            })
        elif count >= 10:
            insights.append({
                'type': 'holdings',
                'title': 'Broad portfolio',
                'message': f'You hold {count} positions. Good spread across names.',
                'icon': 'check',
            })

    except Exception:
        pass
    return insights[:6]  # Cap at 6 insights


def get_stock_insights(stock, latest_price=None, dividend=None, valuation=None, recent_earnings=None):
    """
    Generate stock-level insights from DB (price vs 52w, earnings surprise, dividend, valuation).
    Caller can pass prefetched latest_price, dividend, valuation; otherwise we use stock relations.
    Returns list of dicts: {'type': str, 'title': str, 'message': str, 'icon': str}
    """
    insights = []
    today = timezone.now().date()

    try:
        if latest_price is None and hasattr(stock, 'latest_prices') and stock.latest_prices:
            latest_price = stock.latest_prices[0]
        if latest_price is None:
            latest_price = StockPrice.objects.filter(stock=stock).order_by('-price_date').first()

        if latest_price and latest_price.last_price:
            # 52-week position
            if latest_price.fiftytwo_week_high and latest_price.fiftytwo_week_low:
                try:
                    low = float(latest_price.fiftytwo_week_low)
                    high = float(latest_price.fiftytwo_week_high)
                    current = float(latest_price.last_price)
                    if high > low:
                        pct = ((current - low) / (high - low)) * 100
                        if pct >= 90:
                            insights.append({
                                'type': 'price',
                                'title': 'Near 52-week high',
                                'message': f'Price is in the top 10% of its 52-week range (${low:.2f}–${high:.2f}).',
                                'icon': 'trending_up',
                            })
                        elif pct <= 15:
                            insights.append({
                                'type': 'price',
                                'title': 'Near 52-week low',
                                'message': f'Price is in the lower part of its 52-week range (${low:.2f}–${high:.2f}).',
                                'icon': 'info',
                            })
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

        if dividend is None and hasattr(stock, 'latest_dividends') and stock.latest_dividends:
            dividend = stock.latest_dividends[0]
        if dividend is None:
            dividend = Dividend.objects.filter(stock=stock).order_by('-ex_dividend_date').first()

        if dividend and dividend.amount and float(dividend.amount) > 0:
            y = dividend.yield_percent
            yield_val = float(y) if y is not None else 0
            if yield_val >= 5:
                insights.append({
                    'type': 'dividend',
                    'title': 'High dividend yield',
                    'message': f'Current yield is {yield_val:.1f}%. Strong income potential.',
                    'icon': 'cash',
                })
            elif yield_val >= 3:
                insights.append({
                    'type': 'dividend',
                    'title': 'Solid dividend',
                    'message': f'Yield is {yield_val:.1f}%. Pays {dividend.frequency or "regular"} dividends.',
                    'icon': 'cash',
                })

        if valuation is None and hasattr(stock, 'latest_valuations') and stock.latest_valuations:
            valuation = stock.latest_valuations[0]
        if valuation is None:
            valuation = ValuationMetric.objects.filter(stock=stock).order_by('-metric_date').first()

        if valuation and valuation.pe_ratio is not None:
            try:
                pe = float(valuation.pe_ratio)
                if pe > 0 and pe < 15:
                    insights.append({
                        'type': 'valuation',
                        'title': 'Lower P/E',
                        'message': f'P/E ratio is {pe:.1f}, below typical growth multiples. May indicate value.',
                        'icon': 'chart',
                    })
                elif pe > 25:
                    insights.append({
                        'type': 'valuation',
                        'title': 'Higher P/E',
                        'message': f'P/E ratio is {pe:.1f}. Market is pricing in growth or premium.',
                        'icon': 'chart',
                    })
            except (ValueError, TypeError):
                pass

        if recent_earnings is None:
            recent_earnings = Earnings.objects.filter(
                stock=stock,
                earnings_date__lt=today,
                eps_actual__isnull=False,
                eps_estimate__isnull=False,
            ).exclude(eps_estimate=0).order_by('-earnings_date')[:4]

        if hasattr(recent_earnings, '__iter__') and not isinstance(recent_earnings, list):
            recent_earnings = list(recent_earnings)

        if recent_earnings:
            surprises = []
            for e in recent_earnings:
                if e.eps_estimate and float(e.eps_estimate) != 0 and e.eps_actual is not None:
                    surp = ((float(e.eps_actual) - float(e.eps_estimate)) / abs(float(e.eps_estimate))) * 100
                    surprises.append(surp)
            if surprises:
                avg_surprise = sum(surprises) / len(surprises)
                if avg_surprise > 5:
                    insights.append({
                        'type': 'earnings',
                        'title': 'Earnings beats',
                        'message': f'Recent quarters have beaten EPS estimates on average by {avg_surprise:.1f}%.',
                        'icon': 'trending_up',
                    })
                elif avg_surprise < -5:
                    insights.append({
                        'type': 'earnings',
                        'title': 'Earnings misses',
                        'message': f'Recent quarters have missed EPS estimates on average by {abs(avg_surprise):.1f}%.',
                        'icon': 'info',
                    })

    except Exception:
        pass
    return insights[:5]


def get_stock_news_summary(stock, days=14, max_items=5):
    """
    One-sentence summary of recent news from DB (titles + sentiment). No external API.
    """
    cutoff = timezone.now() - timedelta(days=days)
    news = StockNews.objects.filter(
        stock=stock,
        published_at__gte=cutoff,
    ).order_by('-published_at')[:max_items]

    if not news:
        return None

    positive = sum(1 for n in news if (n.sentiment or '').lower() == 'positive')
    negative = sum(1 for n in news if (n.sentiment or '').lower() == 'negative')
    total = len(news)

    if total == 0:
        return None
    if positive > negative and positive >= 2:
        return f'Recent news ({total} articles) has been mostly positive.'
    if negative > positive and negative >= 2:
        return f'Recent news ({total} articles) has been mostly negative.'
    return f'There are {total} recent article(s) in the last {days} days.'


def get_stock_insights_for_view(stock):
    """
    Convenience: get both insights list and news summary for stock detail page.
    Uses prefetched relations if available (latest_prices, latest_dividends, latest_valuations).
    """
    lp = getattr(stock, 'latest_prices', None)
    ld = getattr(stock, 'latest_dividends', None)
    lv = getattr(stock, 'latest_valuations', None)
    insights = get_stock_insights(
        stock,
        latest_price=lp[0] if lp and len(lp) > 0 else None,
        dividend=ld[0] if ld and len(ld) > 0 else None,
        valuation=lv[0] if lv and len(lv) > 0 else None,
    )
    news_summary = get_stock_news_summary(stock)
    return insights, news_summary
