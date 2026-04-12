"""
Django management command — fetch insider trades from SEDI and store in InsiderTrade.

Usage examples:
  python manage.py fetch_insider_trades --symbol TD
  python manage.py fetch_insider_trades --symbol TD --days 180
  python manage.py fetch_insider_trades --all-stocks --days 90
  python manage.py fetch_insider_trades --all-stocks --limit 20

The command looks up each stock's company_name in SEDI, finds the issuer ID,
downloads transactions, and upserts them into the InsiderTrade table.
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import IntegrityError

from portfolio.models import InsiderTrade, Stock
from portfolio.utils.sedi_scraper import SEDIScraper

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fetch Canadian insider trading data from SEDI (sedi.ca)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            type=str,
            help='Fetch insider trades for a single stock symbol, e.g. --symbol TD',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='How many days back to fetch (default: 90)',
        )
        parser.add_argument(
            '--all-stocks',
            action='store_true',
            help='Fetch insider trades for ALL stocks in the database',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='When using --all-stocks, process at most N stocks (0 = no limit)',
        )
        parser.add_argument(
            '--tsx60-only',
            action='store_true',
            help='When using --all-stocks, only process TSX60 members',
        )

    def handle(self, *args, **options):
        scraper = SEDIScraper()
        days    = options['days']

        # ── Resolve which stocks to process ──────────────────────────────────
        if options['symbol']:
            symbol = options['symbol'].upper()
            try:
                stocks = [Stock.objects.get(symbol=symbol)]
            except Stock.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'Stock {symbol} not found.'))
                return

        elif options['all_stocks']:
            qs = Stock.objects.filter(show_in_listing=True)
            if options['tsx60_only']:
                qs = qs.filter(tsx60_member=True)
            stocks = list(qs.order_by('symbol'))
            if options['limit']:
                stocks = stocks[:options['limit']]
            self.stdout.write(
                self.style.SUCCESS(f'Processing {len(stocks)} stocks...')
            )

        else:
            self.stderr.write(self.style.ERROR(
                'Provide --symbol SYMBOL or --all-stocks'
            ))
            return

        # ── Process each stock ────────────────────────────────────────────────
        total_created = 0
        total_skipped = 0
        errors        = []

        for stock in stocks:
            self.stdout.write(f'  [{stock.symbol}] {stock.company_name} ...')

            try:
                trades, issuer_id = scraper.fetch_trades_for_company(
                    stock.company_name, days_back=days, symbol=stock.symbol
                )

                if not trades:
                    self.stdout.write(f'    → no trades found')
                    continue

                created = 0
                for t in trades:
                    try:
                        obj, was_created = InsiderTrade.objects.get_or_create(
                            stock            = stock,
                            insider_name     = t['insider_name'],
                            transaction_date = t['transaction_date'],
                            shares           = t['shares'],
                            transaction_type = t['transaction_type'],
                            defaults={
                                'insider_title':   t['insider_title'],
                                'security_type':   t['security_type'],
                                'nature_of_trade': t['nature_of_trade'],
                                'price':           t['price'],
                                'total_value':     t['total_value'],
                                'closing_balance': t['closing_balance'],
                                'filing_date':     t['filing_date'],
                                'sedi_issuer_id':  issuer_id,
                            },
                        )
                        if was_created:
                            created += 1
                        else:
                            total_skipped += 1
                    except IntegrityError:
                        total_skipped += 1

                total_created += created
                self.stdout.write(
                    self.style.SUCCESS(f'    → {created} new, {len(trades) - created} already existed')
                )

            except Exception as e:
                msg = f'Error fetching {stock.symbol}: {e}'
                errors.append(msg)
                logger.error(msg)
                self.stdout.write(self.style.WARNING(f'    → ERROR: {e}'))

            # Be polite — extra pause between stocks
            time.sleep(1)

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Created {total_created} new trades | '
            f'Skipped {total_skipped} duplicates | '
            f'{len(errors)} errors'
        ))
        if errors:
            self.stdout.write(self.style.WARNING('Errors:'))
            for e in errors[:10]:
                self.stdout.write(self.style.WARNING(f'  {e}'))
