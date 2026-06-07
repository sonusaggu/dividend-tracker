"""Compute 50-day and 200-day SMAs and store them on the latest StockPrice row.

Designed to be cheap to re-run: one query for all rows in the lookback window,
grouped in memory by stock. Updates only the most recent StockPrice row per stock
so the all-stocks listing can filter "above SMA" with a single subquery.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from portfolio.models import StockPrice


def _sma(prices, window):
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / Decimal(window)


class Command(BaseCommand):
    help = 'Compute 50-day and 200-day SMAs on the latest StockPrice row of every stock.'

    def add_arguments(self, parser):
        parser.add_argument('--symbol', help='Limit to a single stock symbol (e.g. CRCY).')
        parser.add_argument('--lookback-days', type=int, default=300,
                            help='Days of price history to load (default 300, enough for SMA200).')

    def handle(self, *args, **opts):
        cutoff = timezone.now().date() - timedelta(days=opts['lookback_days'])
        qs = StockPrice.objects.filter(price_date__gte=cutoff)
        if opts.get('symbol'):
            qs = qs.filter(stock__symbol=opts['symbol'].upper())
        qs = qs.order_by('stock_id', 'price_date').values_list('stock_id', 'id', 'price_date', 'last_price')

        by_stock = defaultdict(list)
        for stock_id, pk, dt, price in qs:
            by_stock[stock_id].append((pk, dt, price))

        updated = skipped = 0
        with transaction.atomic():
            for stock_id, rows in by_stock.items():
                # rows already sorted by price_date
                prices = [r[2] for r in rows]  # decimals
                latest_pk = rows[-1][0]
                sma50 = _sma(prices, 50)
                sma200 = _sma(prices, 200)
                if sma50 is None and sma200 is None:
                    skipped += 1
                    continue
                StockPrice.objects.filter(pk=latest_pk).update(
                    sma_50=sma50,
                    sma_200=sma200,
                )
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'compute_sma: updated {updated} stocks, skipped {skipped} '
            f'(not enough history within {opts["lookback_days"]}-day window).'
        ))
