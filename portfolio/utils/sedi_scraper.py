"""
Insider trading data fetcher for Canadian stocks.

Source: Yahoo Finance insider-transactions page (which aggregates SEDI data).
Yahoo Finance is accessible without bot protection and returns structured JSON
embedded in the page's __NEXT_DATA__ / app data script block.

URL pattern:
    https://finance.yahoo.com/quote/{TICKER}.TO/insider-transactions

TSX stocks use the .TO suffix on Yahoo (e.g. TD → TD.TO, RY → RY.TO).
For TSX Venture stocks use .V suffix.  We try .TO first, then .V.

Returned trade dict keys:
    insider_name, insider_title, transaction_type ('buy'/'sell'/'grant'/'other'),
    nature_of_trade, shares (int, negative = sell), price (Decimal|None),
    total_value (Decimal|None), closing_balance (None — not in Yahoo data),
    transaction_date (date), filing_date (None — not in Yahoo data)
"""

import json
import logging
import re
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_YAHOO = "https://finance.yahoo.com/quote/{ticker}/insider-transactions"

# Classify transaction text → buy / sell / grant / other
_BUY_RE   = re.compile(r'acqui|purchas|open market buy|automatic purchase|drip|reinvest', re.I)
_SELL_RE  = re.compile(r'dispos|open market sell|sale|sold|redemption|retraction|repurchase|cancelation', re.I)
_GRANT_RE = re.compile(r'grant|award|option|exercise|rsu|dsu|psu|unit', re.I)


def _classify(text: str) -> str:
    if _BUY_RE.search(text):
        return 'buy'
    if _SELL_RE.search(text):
        return 'sell'
    if _GRANT_RE.search(text):
        return 'grant'
    return 'other'


def _parse_name_title(filer_name: str, filer_relation: str) -> tuple[str, str]:
    """
    Yahoo returns names as 'Last (First M)' — convert to 'First Last'.
    e.g. 'Douglas (Paul C)' → 'Paul C Douglas'
    """
    name = filer_name.strip()
    m = re.match(r'^(.+?)\s*\((.+?)\)$', name)
    if m:
        last  = m.group(1).strip()
        first = m.group(2).strip()
        name  = f"{first} {last}"

    # Shorten the very long SEDI relationship strings
    title = filer_relation or ''
    # Common prefixes to strip
    title = re.sub(
        r'^(Director or Senior Officer|10% Security Holder|Significant|Insider)[\w\s,()-]*$',
        lambda x: _short_title(x.group(0)),
        title
    )
    return name, title.strip()


def _short_title(relation: str) -> str:
    """Map verbose SEDI relation strings to short display titles."""
    r = relation.lower()
    if 'chief executive' in r or 'ceo' in r:
        return 'CEO'
    if 'chief financial' in r or 'cfo' in r:
        return 'CFO'
    if 'chief operating' in r or 'coo' in r:
        return 'COO'
    if 'director' in r and 'senior officer' in r:
        return 'Director / Officer'
    if 'director' in r:
        return 'Director'
    if '10%' in r or 'significant' in r:
        return 'Major Shareholder'
    if 'issuer' in r:
        return 'Issuer (Buyback)'
    return relation[:60]  # fall back to truncated original


class SEDIScraper:
    """
    Fetches Canadian insider trading data via Yahoo Finance.

    Usage:
        scraper = SEDIScraper()
        trades, source = scraper.fetch_trades_for_company('Toronto-Dominion Bank', days_back=90)
        # source will be the Yahoo ticker used, e.g. 'TD.TO'
    """

    DELAY = 2.0

    # Known ticker → Yahoo suffix overrides (most TSX stocks use .TO)
    SUFFIX_OVERRIDES = {
        # Add any stocks that don't follow the .TO convention
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self._session_warmed = False

    # ── Public API ────────────────────────────────────────────────────

    def fetch_trades_for_company(self, company_name: str, days_back: int = 90,
                                  symbol: str = '') -> tuple[list[dict], str]:
        """
        Fetch insider trades.  `symbol` is the TSX ticker (e.g. 'TD').
        Returns (trades_list, yahoo_ticker_used).
        """
        # Try .TO suffix first, then .V (TSX Venture)
        suffixes = ['.TO', '.V']
        base = (symbol or company_name.split()[0]).upper().replace('.', '')

        for suffix in suffixes:
            ticker = base + suffix
            trades = self._fetch_for_ticker(ticker, days_back)
            if trades is not None:
                logger.info(f"Fetched {len(trades)} trades for {ticker}")
                return trades, ticker

        logger.warning(f"No Yahoo Finance data found for {symbol or company_name}")
        return [], ''

    # ── Internal ──────────────────────────────────────────────────────

    def _warm_session(self):
        """Visit Yahoo Finance homepage once per scraper instance to get valid cookies."""
        if self._session_warmed:
            return
        try:
            time.sleep(self.DELAY)
            self.session.get('https://finance.yahoo.com/', timeout=15)
            self._session_warmed = True
            time.sleep(1)
        except Exception as e:
            logger.debug(f"Yahoo session warm-up warning: {e}")
            self._session_warmed = True  # don't retry

    def _fetch_for_ticker(self, ticker: str, days_back: int) -> list[dict] | None:
        """
        Return list of trades for `ticker`, or None if the page wasn't found
        (so the caller can try the next suffix).
        """
        self._warm_session()
        url = BASE_YAHOO.format(ticker=ticker)
        try:
            time.sleep(self.DELAY)
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except requests.HTTPError as e:
            if '404' in str(e):
                return None
            logger.warning(f"Yahoo Finance HTTP error for {ticker}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Yahoo Finance request failed for {ticker}: {e}")
            return None

        transactions = self._extract_transactions(resp.text)
        if transactions is None:
            # Page loaded but no data block — might be a valid stock with no trades
            return []

        cutoff = date.today().__class__.fromordinal(
            date.today().toordinal() - days_back
        )

        trades = []
        seen   = set()

        for tx in transactions:
            trade = self._parse_transaction(tx)
            if trade is None:
                continue
            if trade['transaction_date'] < cutoff:
                continue

            # Deduplicate (Yahoo sometimes returns the same trade twice)
            key = (
                trade['insider_name'],
                trade['transaction_date'],
                trade['shares'],
                trade['transaction_type'],
            )
            if key in seen:
                continue
            seen.add(key)
            trades.append(trade)

        return trades

    def _extract_transactions(self, html: str) -> list | None:
        """
        Pull the insiderTransactions.transactions list from Yahoo Finance HTML.

        Yahoo embeds page data as a script tag whose content is a JSON object
        with shape: {"status": 200, "body": "<json-encoded-string>"}
        The inner JSON has: quoteSummary.result[0].insiderTransactions.transactions
        """
        soup = BeautifulSoup(html, 'lxml')

        for script in soup.find_all('script'):
            txt = script.string or ''
            if 'insiderTransactions' not in txt or 'filerName' not in txt:
                continue
            try:
                outer = json.loads(txt)
                body  = json.loads(outer['body'])
                result = body['quoteSummary']['result'][0]
                return result['insiderTransactions']['transactions']
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass

        return None

    def _parse_transaction(self, tx: dict) -> dict | None:
        """Convert a raw Yahoo Finance transaction dict into our InsiderTrade format."""
        try:
            tx_text   = tx.get('transactionText', '')
            shares    = tx.get('shares', {}).get('raw', 0)
            value     = tx.get('value', {}).get('raw')
            tx_type   = _classify(tx_text)
            date_raw  = tx.get('startDate', {}).get('raw')

            if not date_raw or not shares:
                return None

            tx_date = datetime.utcfromtimestamp(date_raw).date()

            filer_name     = tx.get('filerName', '')
            filer_relation = tx.get('filerRelation', '')
            insider_name, insider_title = _parse_name_title(filer_name, filer_relation)

            # Sells should have negative share counts
            if tx_type == 'sell' and shares > 0:
                shares = -shares

            # Derive price from value / shares if possible
            price = None
            if value and shares:
                try:
                    price = round(abs(value) / abs(shares), 4)
                except ZeroDivisionError:
                    pass

            return {
                'insider_name':     insider_name,
                'insider_title':    insider_title,
                'security_type':    'Common Shares',
                'transaction_type': tx_type,
                'nature_of_trade':  tx_text,
                'shares':           shares,
                'price':            price,
                'total_value':      abs(value) if value else None,
                'closing_balance':  None,
                'transaction_date': tx_date,
                'filing_date':      None,
            }
        except Exception as e:
            logger.debug(f"Skipping malformed transaction: {e}")
            return None
