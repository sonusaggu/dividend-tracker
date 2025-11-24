from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, F, Case, When, Value, IntegerField, Subquery, OuterRef, Exists, Max, Min, Sum, Avg, Count, Prefetch
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
import csv
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.db import DatabaseError
from django.conf import settings
from django.views.decorators.cache import cache_control
from datetime import datetime, timedelta, date
from django.core.management import call_command
import subprocess
import logging
import os

from .forms import RegistrationForm
from .models import Stock, Dividend, StockPrice, ValuationMetric, AnalystRating
from .models import UserPortfolio, UserAlert, Watchlist, DividendAlert, NewsletterSubscription, StockNews
from .services import PortfolioService, StockService, AlertService
from .utils.newsletter_utils import DividendNewsletterGenerator
from .utils.news_fetcher import NewsFetcher
from .utils.canadian_tax_calculator import CanadianTaxCalculator

# Set up logging
logger = logging.getLogger(__name__)


@cache_control(max_age=86400)  # Cache for 1 day
def robots_txt(request):
    """Serve robots.txt file"""
    robots_content = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /login/
Disallow: /register/
Disallow: /trigger-daily-scrape/
Disallow: /trigger-dividend-alerts/
Disallow: /trigger-newsletter/
Disallow: /scrape-status/
Disallow: /fetch-news/

# Sitemap
Sitemap: https://dividend.forum/sitemap.xml

# Crawl-delay for aggressive bots
User-agent: *
Crawl-delay: 1
"""
    return HttpResponse(robots_content, content_type='text/plain')


@cache_control(max_age=86400)  # Cache for 1 day
def favicon_view(request):
    """Serve favicon - serve SVG favicon"""
    # Try to serve the SVG favicon from static files
    try:
        from django.contrib.staticfiles import finders
        favicon_path = finders.find('images/favicon.svg')
        if favicon_path:
            with open(favicon_path, 'rb') as f:
                return HttpResponse(f.read(), content_type='image/svg+xml')
    except Exception as e:
        logger.debug(f"Could not serve favicon: {e}")
    
    # Return 204 No Content if favicon doesn't exist
    return HttpResponse(status=204)


def login_view(request):
    """User login view with CSRF protection"""
    # If user is already authenticated, redirect to dashboard
    if request.user.is_authenticated:
        next_url = request.GET.get('next', 'dashboard')
        return redirect(next_url)
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        if not username or not password:
            messages.error(request, 'Username and password are required.')
            # Preserve next parameter in GET
            context = {'next': request.POST.get('next') or request.GET.get('next')}
            return render(request, 'login.html', context)
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect to next page if provided, otherwise to dashboard
            next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard'
            # Validate next URL to prevent open redirects
            # Only allow relative URLs (starting with /) or named URL patterns
            if next_url.startswith('http://') or next_url.startswith('https://'):
                # Block external URLs - only allow same domain
                if not next_url.startswith(request.build_absolute_uri('/')):
                    next_url = 'dashboard'
            elif not next_url.startswith('/') and not next_url:
                # If it's not a relative URL and not empty, use dashboard
                next_url = 'dashboard'
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
            # Don't reveal whether username exists
            logger.warning(f"Failed login attempt for username: {username}")
    
    # Preserve next parameter for GET requests
    context = {'next': request.GET.get('next')}
    return render(request, 'login.html', context)

@csrf_protect
def register_view(request):
    """User registration view with CSRF protection"""
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                # === EMAIL CHECK ===
                email = form.cleaned_data.get('email', '').lower()
                allowed_domains = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'icloud.com']
                
                domain = email.split('@')[-1] if '@' in email else ''
                if domain not in allowed_domains:
                    messages.error(request, 'Please use Gmail, Outlook, Hotmail, Yahoo, or iCloud for registration.')
                    return render(request, 'register.html', {'form': form})
                # === END CHECK ===
                
                user = form.save()
                login(request, user)
                messages.success(request, 'Registration successful!')
                return redirect('dashboard')
            except Exception as e:
                logger.error(f"Error during user registration: {e}")
                messages.error(request, 'An error occurred during registration. Please try again.')
        else:
            # Log form errors for debugging (not shown to user)
            logger.debug(f"Registration form errors: {form.errors}")
    else:
        form = RegistrationForm()
    
    return render(request, 'register.html', {'form': form})

def logout_view(request):
    """User logout view"""
    logout(request)
    return redirect('home') 

def home_view(request):
    """Home page with upcoming dividends - Fully optimized"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    try:
        today = timezone.now().date()
        dividends_with_data = StockService.get_upcoming_dividends(days=30, limit=12)
        
        # Prepare data efficiently
        upcoming_dividends = []
        for dividend in dividends_with_data:
            # Format yield as percentage (multiply by 100 if it's a decimal)
            yield_value = dividend.yield_percent
            if yield_value and isinstance(yield_value, (int, float)):
                # If yield is already a percentage (0-100), use as is
                # If it's a decimal (0-1), multiply by 100
                if yield_value < 1:
                    yield_value = yield_value * 100
            
            upcoming_dividends.append({
                'symbol': dividend.stock.symbol,
                'company_name': dividend.stock.company_name,
                'last_price': dividend.latest_price or 'N/A',
                'dividend_amount': dividend.amount,
                'dividend_yield': yield_value,
                'ex_dividend_date': dividend.ex_dividend_date,
                'days_until': (dividend.ex_dividend_date - today).days if dividend.ex_dividend_date else None,
                'frequency': dividend.frequency
            })
            
    except DatabaseError as e:
        logger.error(f"Database error in home view: {e}")
        messages.error(request, 'A temporary error occurred. Please try again later.')
        upcoming_dividends = []
    except Exception as e:
        logger.error(f"Unexpected error in home view: {e}")
        upcoming_dividends = []
    
    context = {'upcoming_dividends': upcoming_dividends}
    return render(request, 'home.html', context)

def all_stocks_view(request):
    """Optimized: View all stocks with pagination, search, sector filtering, and sorting"""

    # --- 1️⃣ Fetch unique sectors once
    sectors = list(
        Stock.objects.exclude(sector='')
        .values_list('sector', flat=True)
        .distinct()
        .order_by('sector')
    )

    # --- 2️⃣ Validate query parameters
    search_query = request.GET.get('search', '').strip()
    sector_filter = request.GET.get('sector', '')
    sort_by = request.GET.get('sort_by', 'dividend_date')

    valid_sort_options = ['symbol', 'yield', 'sector', 'dividend_date', 'dividend_amount']
    if sort_by not in valid_sort_options:
        sort_by = 'dividend_date'

    # --- 3️⃣ Base queryset with annotations
    stocks = StockService.get_stocks_with_annotations()

    # --- 4️⃣ Apply filters
    if search_query:
        stocks = stocks.filter(
            Q(symbol__icontains=search_query)
            | Q(company_name__icontains=search_query)
            | Q(code__icontains=search_query)
        )

    if sector_filter in sectors:
        stocks = stocks.filter(sector=sector_filter)
    else:
        sector_filter = ''

    # --- 7️⃣ Sorting map (simpler than if/elif chain)
    sort_map = {
        'symbol': ['symbol'],
        'yield': ['-latest_dividend_yield', 'symbol'],
        'sector': ['sector', 'symbol'],
        'dividend_amount': ['-latest_dividend_amount', 'symbol'],
        'dividend_date': [
            Case(
                When(upcoming_dividend_date__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ),
            'upcoming_dividend_date', 'symbol'
        ],
    }
    stocks = stocks.order_by(*sort_map.get(sort_by, ['symbol']))

    # --- 8️⃣ Pagination (handles bad pages gracefully)
    paginator = Paginator(stocks, 24)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # --- 9️⃣ Prepare context list — already annotated, no extra DB calls
    stocks_with_data = [
        {
            'stock': stock,
            'latest_dividend': (
                {
                    'amount': stock.latest_dividend_amount,
                    'yield_percent': stock.latest_dividend_yield,
                    'ex_dividend_date': stock.latest_dividend_date,
                    'frequency': stock.latest_dividend_frequency,
                } if stock.latest_dividend_amount else None
            ),
            'upcoming_dividend_date': stock.upcoming_dividend_date,
            'latest_price': (
                {
                    'price': stock.latest_price_value,
                    'date': stock.latest_price_date,
                } if stock.latest_price_value else None
            ),
            'has_dividend': stock.has_dividend,
        }
        for stock in page_obj
    ]

    # --- 🔟 Stats (could be cached if large)
    context = {
        'stocks_with_dividends': stocks_with_data,
        'page_obj': page_obj,
        'search_query': search_query,
        'sector_filter': sector_filter,
        'sort_by': sort_by,
        'sectors': sectors,
        'total_stocks_count': Stock.objects.count(),
        'dividend_stocks_count': Dividend.objects.values('stock').distinct().count(),
        'sectors_count': len(sectors),
    }

    return render(request, 'all_stocks.html', context)


def stock_detail(request, symbol):
    """Detailed view for a single stock - Optimized with single query"""
    # Validate symbol format
    if not symbol or not isinstance(symbol, str) or len(symbol) > 10:
        return HttpResponseBadRequest("Invalid stock symbol")
    
    # Optimized: Use prefetch_related to get all related data in fewer queries
    stock = get_object_or_404(
        Stock.objects.prefetch_related(
            Prefetch('prices', queryset=StockPrice.objects.order_by('-price_date'), to_attr='latest_prices'),
            Prefetch('dividends', queryset=Dividend.objects.order_by('-ex_dividend_date'), to_attr='latest_dividends'),
            Prefetch('valuations', queryset=ValuationMetric.objects.order_by('-metric_date'), to_attr='latest_valuations'),
            Prefetch('analyst_ratings', queryset=AnalystRating.objects.order_by('-rating_date'), to_attr='latest_ratings'),
        ),
        symbol=symbol.upper()
    )
    
    # Get latest data from prefetched attributes (no additional queries)
    latest_price = stock.latest_prices[0] if stock.latest_prices else None
    dividend = stock.latest_dividends[0] if stock.latest_dividends else None
    valuation = stock.latest_valuations[0] if stock.latest_valuations else None
    analyst_rating = stock.latest_ratings[0] if stock.latest_ratings else None
    
    # Check if stock is in user's watchlist and portfolio - optimized with single query
    in_watchlist = False
    in_portfolio = False
    has_dividend_alert = False
    portfolio_item = None
    portfolio_total_value = None
    
    if request.user.is_authenticated:
        # Get all user-related data in one query using select_related
        portfolio_item = UserPortfolio.objects.filter(
            user=request.user, stock=stock
        ).select_related('stock').first()
        in_portfolio = portfolio_item is not None
        
        # Calculate total value if in portfolio
        if portfolio_item and latest_price and portfolio_item.shares_owned:
            portfolio_total_value = float(portfolio_item.shares_owned * latest_price.last_price)
        
        # Combine exists() checks - could be optimized further but exists() is already efficient
        in_watchlist = Watchlist.objects.filter(user=request.user, stock=stock).exists()
        has_dividend_alert = DividendAlert.objects.filter(
            user=request.user, stock=stock, is_active=True
        ).exists()
    
    context = {
        'stock': stock,
        'latest_price': latest_price,
        'dividend': dividend,
        'valuation': valuation,
        'analyst_rating': analyst_rating,
        'in_watchlist': in_watchlist,
        'in_portfolio': in_portfolio,
        'has_dividend_alert': has_dividend_alert,
        'portfolio_item': portfolio_item,
        'portfolio_total_value': portfolio_total_value,
        'today': timezone.now().date(),
    }
    
    return render(request, 'stock_detail.html', context)


def dividend_history(request, symbol):
    """Display dividend history for a stock"""
    # Validate symbol format
    if not symbol or not isinstance(symbol, str) or len(symbol) > 10:
        return HttpResponseBadRequest("Invalid stock symbol")
    
    stock = get_object_or_404(Stock, symbol=symbol.upper())
    
    # Get all dividends ordered by ex-dividend date (most recent first)
    dividends = Dividend.objects.filter(stock=stock).order_by('-ex_dividend_date')
    
    # Calculate statistics using database aggregation (much faster)
    stats = dividends.aggregate(
        total_count=Count('id'),
        total_amount=Sum('amount'),
        avg_amount=Avg('amount'),
        max_amount=Max('amount'),
        min_amount=Min('amount')
    )
    
    total_dividends = stats['total_count'] or 0
    total_amount = float(stats['total_amount'] or 0)
    avg_amount = float(stats['avg_amount'] or 0)
    max_amount = float(stats['max_amount'] or 0)
    min_amount = float(stats['min_amount'] or 0)
    
    # Get frequency distribution using database aggregation
    frequency_dist = dict(
        dividends.values('frequency')
        .annotate(count=Count('id'))
        .values_list('frequency', 'count')
    )
    # Handle None frequencies
    if None in frequency_dist:
        frequency_dist['Unknown'] = frequency_dist.pop(None)
    
    # Calculate annual dividend using database aggregation
    current_year = timezone.now().year
    annual_dividend = float(
        dividends.filter(ex_dividend_date__year=current_year)
        .aggregate(total=Sum('amount'))['total'] or 0
    )
    
    # Get latest price for yield calculation (single query)
    latest_price = StockPrice.objects.filter(stock=stock).order_by('-price_date').first()
    current_yield = None
    if latest_price and latest_price.last_price and annual_dividend > 0:
        current_yield = (annual_dividend / float(latest_price.last_price)) * 100
    
    # Paginate dividends (20 per page)
    paginator = Paginator(dividends, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'stock': stock,
        'dividends': page_obj,
        'total_dividends': total_dividends,
        'total_amount': total_amount,
        'avg_amount': avg_amount,
        'max_amount': max_amount,
        'min_amount': min_amount,
        'frequency_dist': frequency_dist,
        'annual_dividend': annual_dividend,
        'current_yield': current_yield,
        'latest_price': latest_price,
        'today': timezone.now().date(),
    }
    
    return render(request, 'dividend_history.html', context)


@login_required
def dividend_calendar(request):
    """Display dividend calendar view with monthly/weekly calendar"""
    from calendar import monthrange, month_name
    from collections import defaultdict
    
    # Get filter type (all, portfolio, watchlist)
    filter_type = request.GET.get('filter', 'all')  # all, portfolio, watchlist
    
    # Get month/year from query params (default to current month)
    today = timezone.now().date()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        # Validate month/year
        if month < 1 or month > 12:
            month = today.month
        if year < 2020 or year > 2100:
            year = today.year
    except (ValueError, TypeError):
        year = today.year
        month = today.month
    
    # Calculate date range for the month
    first_day = date(year, month, 1)
    last_day_num = monthrange(year, month)[1]
    last_day = date(year, month, last_day_num)
    
    # Get start of calendar (first Monday before or on first day)
    calendar_start = first_day - timedelta(days=first_day.weekday())
    # Get end of calendar (last Sunday after or on last day)
    calendar_end = last_day + timedelta(days=(6 - last_day.weekday()))
    
    # Build query for dividends
    dividend_query = Dividend.objects.filter(
        ex_dividend_date__gte=calendar_start,
        ex_dividend_date__lte=calendar_end
    ).select_related('stock').order_by('ex_dividend_date', 'stock__symbol')
    
    # Apply filters
    if filter_type == 'portfolio' and request.user.is_authenticated:
        # Get user's portfolio stock IDs first, then filter dividends
        portfolio_stock_ids = list(UserPortfolio.objects.filter(
            user=request.user
        ).values_list('stock_id', flat=True))
        if portfolio_stock_ids:
            dividend_query = dividend_query.filter(stock_id__in=portfolio_stock_ids)
        else:
            # No stocks in portfolio, return empty queryset
            dividend_query = dividend_query.none()
    elif filter_type == 'watchlist' and request.user.is_authenticated:
        # Get user's watchlist stock IDs first, then filter dividends
        watchlist_stock_ids = list(Watchlist.objects.filter(
            user=request.user
        ).values_list('stock_id', flat=True))
        if watchlist_stock_ids:
            dividend_query = dividend_query.filter(stock_id__in=watchlist_stock_ids)
        else:
            # No stocks in watchlist, return empty queryset
            dividend_query = dividend_query.none()
    
    # Group dividends by date
    dividends_by_date = defaultdict(list)
    total_amount_by_date = defaultdict(float)
    
    for dividend in dividend_query:
        if dividend.ex_dividend_date:
            date_key = dividend.ex_dividend_date
            dividends_by_date[date_key].append(dividend)
            total_amount_by_date[date_key] += float(dividend.amount or 0)
    
    # Build calendar grid
    calendar_days = []
    current_date = calendar_start
    
    while current_date <= calendar_end:
        day_dividends = dividends_by_date.get(current_date, [])
        day_total = total_amount_by_date.get(current_date, 0)
        is_current_month = current_date.month == month
        
        calendar_days.append({
            'date': current_date,
            'day': current_date.day,
            'is_current_month': is_current_month,
            'is_today': current_date == today,
            'dividends': day_dividends,
            'dividend_count': len(day_dividends),
            'total_amount': day_total,
        })
        
        current_date += timedelta(days=1)
    
    # Calculate statistics
    total_dividends = dividend_query.count()
    total_amount = sum(total_amount_by_date.values())
    
    # Get unique stocks
    unique_stocks = set()
    for dividends in dividends_by_date.values():
        for div in dividends:
            unique_stocks.add(div.stock)
    
    # Calculate previous/next month
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year
    
    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year
    
    context = {
        'year': year,
        'month': month,
        'month_name': month_name[month],
        'calendar_days': calendar_days,
        'filter_type': filter_type,
        'total_dividends': total_dividends,
        'total_amount': total_amount,
        'unique_stocks_count': len(unique_stocks),
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
        'today': today,
    }
    
    return render(request, 'dividend_calendar.html', context)

@login_required
@require_POST
def toggle_watchlist(request, stock_id):
    """Toggle stock in user's watchlist with max 10 stocks limit"""
    try:
        # Validate stock_id is a positive integer
        stock_id = int(stock_id)
        if stock_id <= 0:
            return JsonResponse({'status': 'error', 'message': 'Invalid stock ID'}, status=400)
            
        stock = get_object_or_404(Stock, id=stock_id)
        
        # Check if user already has this stock in watchlist
        existing_watchlist_item = Watchlist.objects.filter(user=request.user, stock=stock).first()
        
        if existing_watchlist_item:
            # Remove from watchlist
            existing_watchlist_item.delete()
            return JsonResponse({'status': 'removed', 'message': f'Removed {stock.symbol} from watchlist'})
        else:
            # Check if user can add more watchlist items
            if not AlertService.can_add_watchlist_item(request.user):
                return JsonResponse({
                    'status': 'error', 
                    'message': f'Maximum limit of {AlertService.MAX_WATCHLIST_ITEMS} watchlist stocks reached. Please remove some stocks first.'
                }, status=400)
            
            # Add to watchlist
            Watchlist.objects.create(user=request.user, stock=stock)
            return JsonResponse({'status': 'added', 'message': f'Added {stock.symbol} to watchlist'})
    
    except (ValueError, TypeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid stock ID'}, status=400)
    except Exception as e:
        logger.error(f"Error toggling watchlist: {e}")
        return JsonResponse({'status': 'error', 'message': 'An error occurred'}, status=500)

@login_required
@require_POST
def add_to_portfolio(request, symbol):
    """Add or update stock in user's portfolio"""
    # Validate symbol format
    if not symbol or not isinstance(symbol, str) or len(symbol) > 10:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid stock symbol'
        }, status=400)
    
    stock = get_object_or_404(Stock, symbol=symbol.upper())
    
    try:
        shares_owned = int(request.POST.get('shares_owned', 0))
        average_cost = float(request.POST.get('average_cost', 0))
        notes = request.POST.get('notes', '')[:500]  # Limit notes length
        
        # Validate input values
        if shares_owned <= 0:
            return JsonResponse({
                'status': 'error',
                'message': 'Shares owned must be a positive number'
            }, status=400)
            
        if average_cost <= 0:
            return JsonResponse({
                'status': 'error',
                'message': 'Average cost must be a positive number'
            }, status=400)
        
        portfolio_item, created = UserPortfolio.objects.update_or_create(
            user=request.user,
            stock=stock,
            defaults={
                'shares_owned': shares_owned,
                'average_cost': average_cost,
                'notes': notes
            }
        )
        
        return JsonResponse({
            'status': 'success', 
            'message': 'Portfolio updated successfully!'
        })
    
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid input in add_to_portfolio: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid input values. Please check your entries.'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in add_to_portfolio: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'An error occurred while updating your portfolio.'
        }, status=500)

@login_required
def watchlist_view(request):
    """View user's watchlist - Optimized with prefetch_related and annotations"""
    try:
        # Get user's portfolio stock IDs for efficient checking
        portfolio_stock_ids = set(
            UserPortfolio.objects.filter(user=request.user)
            .values_list('stock_id', flat=True)
        )
        
        # Use service layer for optimized query
        watchlist_items = PortfolioService.get_watchlist_with_annotations(request.user)
        
        # Prepare data efficiently
        watchlist_data = []
        dividend_stocks_count = 0
        sectors = set()
        
        for item in watchlist_items:
            in_portfolio = item.stock_id in portfolio_stock_ids
            
            latest_price = None
            if item.latest_price_value:
                latest_price = type('obj', (object,), {
                    'last_price': item.latest_price_value,
                    'price_date': item.latest_price_date
                })()
            
            latest_dividend = None
            if item.latest_dividend_amount:
                latest_dividend = type('obj', (object,), {
                    'amount': item.latest_dividend_amount,
                    'yield_percent': item.latest_dividend_yield,
                    'ex_dividend_date': item.latest_dividend_date,
                    'frequency': item.latest_dividend_frequency
                })()
                dividend_stocks_count += 1
            
            if item.stock.sector:
                sectors.add(item.stock.sector)
            
            watchlist_data.append({
                'stock': item.stock,
                'latest_price': latest_price,
                'latest_dividend': latest_dividend,
                'in_portfolio': in_portfolio,
                'watchlist_item': item
            })
        
        # Count stocks in portfolio
        in_portfolio_count = sum(1 for item in watchlist_data if item['in_portfolio'])
        
        return render(request, 'watchlist.html', {
            'watchlist_items': watchlist_data,
            'dividend_stocks_count': dividend_stocks_count,
            'sectors_count': len(sectors),
            'watchlist_count': len(watchlist_items),
            'in_portfolio_count': in_portfolio_count,
        })
    
    except Exception as e:
        logger.error(f"Error in watchlist_view: {e}")
        messages.error(request, 'An error occurred while loading your watchlist.')
        return redirect('dashboard')

@login_required
def portfolio_view(request):
    """View user's portfolio - Optimized with annotations to avoid N+1 queries"""
    try:
        # Use service layer for optimized query
        portfolio_items = PortfolioService.get_portfolio_with_annotations(request.user)
        
        # Calculate portfolio statistics
        total_value = 0
        total_investment = 0
        annual_dividend_income = 0
        
        portfolio_data = []
        for item in portfolio_items:
            # Calculate current value and gains
            current_value = 0
            if item.latest_price_value and item.shares_owned:
                current_value = float(item.shares_owned * item.latest_price_value)
            
            investment_value = 0
            if item.average_cost and item.shares_owned:
                investment_value = float(item.shares_owned * item.average_cost)
            
            gain_loss = current_value - investment_value
            
            # Calculate dividend income using service
            dividend_income = PortfolioService.calculate_annual_dividend(
                item.latest_dividend_amount,
                item.shares_owned,
                item.latest_dividend_frequency
            )
            
            # Create mock objects for template compatibility
            latest_price = None
            if item.latest_price_value:
                latest_price = type('obj', (object,), {
                    'last_price': item.latest_price_value,
                    'price_date': item.latest_price_date
                })()
            
            latest_dividend = None
            if item.latest_dividend_amount:
                latest_dividend = type('obj', (object,), {
                    'amount': item.latest_dividend_amount,
                    'yield_percent': item.latest_dividend_yield,
                    'frequency': item.latest_dividend_frequency,
                    'ex_dividend_date': item.latest_dividend_date
                })()
            
            # Calculate percentage gain/loss (ROI)
            roi_percent = 0
            if investment_value > 0:
                roi_percent = (gain_loss / investment_value) * 100
            
            # Calculate yield on cost
            yield_on_cost = 0
            if investment_value > 0 and dividend_income > 0:
                yield_on_cost = (dividend_income / investment_value) * 100
            
            # Calculate portfolio allocation percentage
            portfolio_allocation = 0  # Will be calculated after total_value
            
            # Calculate expected dividend for upcoming payment
            expected_dividend = 0
            if item.latest_dividend_amount and item.shares_owned:
                expected_dividend = float(item.latest_dividend_amount * item.shares_owned)
            
            portfolio_data.append({
                'item': item,
                'current_value': current_value,
                'investment_value': investment_value,
                'gain_loss': gain_loss,
                'roi_percent': roi_percent,
                'dividend_income': dividend_income,
                'yield_on_cost': yield_on_cost,
                'expected_dividend': expected_dividend,
                'latest_price': latest_price,
                'latest_dividend': latest_dividend
            })
            
            total_value += current_value
            total_investment += investment_value
            annual_dividend_income += dividend_income
        
        # Calculate portfolio allocation for each item
        for data in portfolio_data:
            if total_value > 0:
                data['portfolio_allocation'] = (data['current_value'] / total_value) * 100
            else:
                data['portfolio_allocation'] = 0
        
        # Calculate overall metrics
        total_gain_loss = total_value - total_investment
        total_roi_percent = 0
        if total_investment > 0:
            total_roi_percent = (total_gain_loss / total_investment) * 100
        
        portfolio_yield = 0
        if total_value > 0 and annual_dividend_income > 0:
            portfolio_yield = (annual_dividend_income / total_value) * 100
        
        # Calculate yield on cost
        yield_on_cost = 0
        if total_investment > 0 and annual_dividend_income > 0:
            yield_on_cost = (annual_dividend_income / total_investment) * 100
        
        # Calculate monthly dividend income
        monthly_dividend_income = annual_dividend_income / 12 if annual_dividend_income > 0 else 0
        
        # Calculate sector allocation
        sector_allocation = {}
        for data in portfolio_data:
            sector = data['item'].stock.sector or 'Unknown'
            if sector not in sector_allocation:
                sector_allocation[sector] = 0
            sector_allocation[sector] += data['current_value']
        
        # Convert to percentage
        sector_allocation_percent = {}
        for sector, value in sector_allocation.items():
            if total_value > 0:
                sector_allocation_percent[sector] = (value / total_value) * 100
        
        # Prepare sector allocation data for chart (with values)
        sector_chart_data = []
        for sector, percent in sector_allocation_percent.items():
            sector_value = sector_allocation.get(sector, 0)
            sector_chart_data.append({
                'sector': sector,
                'percent': round(percent, 2),
                'value': round(sector_value, 2)
            })
        # Sort by value descending
        sector_chart_data.sort(key=lambda x: x['value'], reverse=True)
        
        # Calculate dividend income projection
        dividend_projection = PortfolioService.calculate_dividend_projection(portfolio_items, months=12)
        
        # Calculate total projected income
        total_projected_income = 0
        if dividend_projection:
            total_projected_income = dividend_projection[-1]['cumulative'] if dividend_projection else 0
        
        return render(request, 'portfolio.html', {
            'portfolio_items': portfolio_data,
            'total_value': total_value,
            'total_investment': total_investment,
            'total_gain_loss': total_gain_loss,
            'total_roi_percent': total_roi_percent,
            'annual_dividend_income': annual_dividend_income,
            'monthly_dividend_income': monthly_dividend_income,
            'portfolio_yield': portfolio_yield,
            'yield_on_cost': yield_on_cost,
            'sector_allocation': sector_allocation_percent,
            'sector_chart_data': sector_chart_data,  # For pie chart
            'dividend_projection': dividend_projection,  # For projection chart
            'total_projected_income': total_projected_income,  # Total projected income
        })
    
    except Exception as e:
        logger.error(f"Error in portfolio_view: {e}")
        messages.error(request, 'An error occurred while loading your portfolio.')
        return redirect('dashboard')


@login_required
def export_portfolio(request):
    """Export portfolio to CSV"""
    try:
        portfolio_items = PortfolioService.get_portfolio_with_annotations(request.user)
        
        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="portfolio_export.csv"'
        
        writer = csv.writer(response)
        # Write header
        writer.writerow([
            'Symbol', 'Company Name', 'Sector', 'Shares Owned', 'Average Cost',
            'Current Price', 'Current Value', 'Investment Value', 'Gain/Loss',
            'ROI %', 'Portfolio Allocation %', 'Annual Dividend Income',
            'Yield on Cost %', 'Dividend Yield %'
        ])
        
        # Calculate totals
        total_value = 0
        total_investment = 0
        
        for item in portfolio_items:
            current_value = 0
            if item.latest_price_value and item.shares_owned:
                current_value = float(item.shares_owned * item.latest_price_value)
                total_value += current_value
            
            investment_value = 0
            if item.average_cost and item.shares_owned:
                investment_value = float(item.shares_owned * item.average_cost)
                total_investment += investment_value
            
            gain_loss = current_value - investment_value
            roi_percent = (gain_loss / investment_value * 100) if investment_value > 0 else 0
            allocation = (current_value / total_value * 100) if total_value > 0 else 0
            
            dividend_income = PortfolioService.calculate_annual_dividend(
                item.latest_dividend_amount,
                item.shares_owned,
                item.latest_dividend_frequency
            )
            
            yield_on_cost = (dividend_income / investment_value * 100) if investment_value > 0 else 0
            dividend_yield = item.latest_dividend_yield or 0
            
            writer.writerow([
                item.stock.symbol,
                item.stock.company_name,
                item.stock.sector or 'N/A',
                item.shares_owned,
                f"{item.average_cost:.2f}" if item.average_cost else '0.00',
                f"{item.latest_price_value:.2f}" if item.latest_price_value else 'N/A',
                f"{current_value:.2f}",
                f"{investment_value:.2f}",
                f"{gain_loss:.2f}",
                f"{roi_percent:.2f}",
                f"{allocation:.2f}",
                f"{dividend_income:.2f}",
                f"{yield_on_cost:.2f}",
                f"{dividend_yield:.3f}" if dividend_yield else 'N/A'
            ])
        
        # Write summary row
        total_gain_loss = total_value - total_investment
        total_roi = (total_gain_loss / total_investment * 100) if total_investment > 0 else 0
        
        writer.writerow([])  # Empty row
        writer.writerow(['TOTAL', '', '', '', '', '', f"{total_value:.2f}", f"{total_investment:.2f}",
                        f"{total_gain_loss:.2f}", f"{total_roi:.2f}", '100.00', '', '', ''])
        
        return response
    
    except Exception as e:
        logger.error(f"Error exporting portfolio: {e}")
        messages.error(request, 'Error exporting portfolio. Please try again.')
        return redirect('portfolio')


@login_required
@require_POST
def check_watchlist_status(request, stock_id):
    """Check if stock is in user's watchlist"""
    try:
        # Validate stock_id is a positive integer
        stock_id = int(stock_id)
        if stock_id <= 0:
            return JsonResponse({'error': 'Invalid stock ID'}, status=400)
            
        stock = get_object_or_404(Stock, id=stock_id)
        in_watchlist = Watchlist.objects.filter(user=request.user, stock=stock).exists()
        
        return JsonResponse({'in_watchlist': in_watchlist})
    
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid stock ID'}, status=400)
    except Exception as e:
        logger.error(f"Error in check_watchlist_status: {e}")
        return JsonResponse({'error': 'An error occurred'}, status=500)

@login_required
@require_POST
def set_alert(request, symbol):
    """Set alert for a stock with max 5 alerts per user limit"""
    # Validate symbol format
    if not symbol or not isinstance(symbol, str) or len(symbol) > 10:
        messages.error(request, 'Invalid stock symbol.')
        return redirect('all_stocks')
    
    try:
        stock = get_object_or_404(Stock, symbol=symbol.upper())
        alert_type = request.POST.get('alert_type')
        threshold = request.POST.get('threshold')
        days_advance = request.POST.get('days_advance', 1)
        
        # Validate alert_type
        valid_alert_types = ['price', 'dividend']  # Add all valid types
        if alert_type not in valid_alert_types:
            messages.error(request, 'Invalid alert type.')
            return redirect('stock_detail', symbol=symbol)
        
        # For dividend alerts, check the limit
        if alert_type == 'dividend':
            # Check if user already has this alert
            existing_alert = UserAlert.objects.filter(
                user=request.user, 
                stock=stock, 
                alert_type='dividend'
            ).first()
            
            if existing_alert:
                # Update existing alert
                existing_alert.threshold = threshold
                existing_alert.days_advance = days_advance
                existing_alert.save()
                messages.success(request, f'Dividend alert for {stock.symbol} has been updated.')
                return redirect('stock_detail', symbol=symbol)
            
            # Check if user can add more dividend alerts
            if not AlertService.can_add_dividend_alert(request.user):
                messages.error(request, f'Maximum limit of {AlertService.MAX_DIVIDEND_ALERTS} dividend alerts reached. Please remove some alerts first.')
                return redirect('stock_detail', symbol=symbol)
        
        # Validate threshold if it's a price alert
        if alert_type == 'price':
            try:
                threshold = float(threshold)
                if threshold <= 0:
                    messages.error(request, 'Price threshold must be positive.')
                    return redirect('stock_detail', symbol=symbol)
            except (ValueError, TypeError):
                messages.error(request, 'Invalid price threshold.')
                return redirect('stock_detail', symbol=symbol)
        
        # Validate days_advance
        try:
            days_advance = int(days_advance)
            if days_advance < 1 or days_advance > 30:
                messages.error(request, 'Days advance must be between 1 and 30.')
                return redirect('stock_detail', symbol=symbol)
        except (ValueError, TypeError):
            messages.error(request, 'Invalid days advance value.')
            return redirect('stock_detail', symbol=symbol)
        
        alert, created = UserAlert.objects.get_or_create(
            user=request.user,
            stock=stock,
            alert_type=alert_type,
            defaults={
                'threshold': threshold,
                'days_advance': days_advance
            }
        )
        
        if created:
            messages.success(request, f'Alert for {stock.symbol} has been set successfully.')
        else:
            messages.info(request, f'Alert for {stock.symbol} already exists and has been updated.')
            
        return redirect('stock_detail', symbol=symbol)
        
    except Stock.DoesNotExist:
        messages.error(request, 'Stock not found.')
        return redirect('all_stocks')
    
    except Exception as e:
        logger.error(f"Error setting alert: {e}")
        messages.error(request, 'An error occurred while setting the alert.')
        return redirect('stock_detail', symbol=symbol)

@login_required
def dashboard(request):
    """User dashboard with portfolio overview - Optimized with annotations"""
    try:
        # Use service layer for optimized query
        portfolio_items = PortfolioService.get_portfolio_with_annotations(request.user)
        
        # Calculate portfolio metrics
        total_value = 0
        annual_dividends = 0
        total_holdings = portfolio_items.count()
        
        for item in portfolio_items:
            # Calculate current value
            if item.latest_price_value and item.shares_owned:
                item.current_value = float(item.latest_price_value * item.shares_owned)
                total_value += item.current_value
            
            # Calculate annual dividends using service
            annual_dividends += PortfolioService.calculate_annual_dividend(
                item.latest_dividend_amount,
                item.shares_owned,
                item.latest_dividend_frequency
            )
        
        # Get upcoming dividends for user's stocks - optimized query
        today = timezone.now().date()
        thirty_days_later = today + timedelta(days=30)
        
        user_dividends = Dividend.objects.filter(
            stock__userportfolio__user=request.user,
            ex_dividend_date__gte=today,
            ex_dividend_date__lte=thirty_days_later
        ).select_related('stock').order_by('ex_dividend_date')[:3]  # Limit at DB level
        
        upcoming_dividends = [
            {
                'stock': dividend.stock,
                'amount': dividend.amount,
                'ex_dividend_date': dividend.ex_dividend_date,
                'days_until': (dividend.ex_dividend_date - today).days
            }
            for dividend in user_dividends
        ]
        
        # Get watchlist stocks with prices - optimized with prefetch to avoid N+1
        watchlist_items = Watchlist.objects.filter(user=request.user).select_related('stock').prefetch_related(
            Prefetch('stock__prices', queryset=StockPrice.objects.order_by('-price_date'), to_attr='latest_prices')
        )[:5]
        watchlist_stocks = []
        for item in watchlist_items:
            stock = item.stock
            latest_price = stock.latest_prices[0] if stock.latest_prices else None
            watchlist_stocks.append({
                'stock': stock,
                'latest_price': latest_price.last_price if latest_price else None,
                'price_date': latest_price.price_date if latest_price else None,
            })
        
        # Calculate additional metrics
        total_investment = sum(
            float(item.shares_owned * item.average_cost) 
            for item in portfolio_items 
            if item.average_cost and item.shares_owned
        )
        total_gain_loss = total_value - total_investment
        percent_gain_loss = (total_gain_loss / total_investment * 100) if total_investment > 0 else 0
        dividend_yield = (annual_dividends / total_value * 100) if total_value > 0 else 0
        
        # Get unique sectors
        sectors = set()
        for item in portfolio_items:
            if item.stock.sector:
                sectors.add(item.stock.sector)
        sectors_count = len(sectors)
        
        # Get recent news for portfolio and watchlist stocks (last 7 days)
        portfolio_stock_ids = [item.stock.id for item in portfolio_items]
        watchlist_stock_ids = [item.stock.id for item in watchlist_items]
        all_stock_ids = list(set(portfolio_stock_ids + watchlist_stock_ids))
        
        cutoff_date = timezone.now() - timedelta(days=7)
        recent_news = StockNews.objects.filter(
            stock_id__in=all_stock_ids,
            published_at__gte=cutoff_date
        ).select_related('stock').order_by('-published_at')[:5]
        
        # Get real performance data from snapshots (only if model exists)
        performance_snapshots = None
        try:
            performance_snapshots = PortfolioService.get_portfolio_performance_history(request.user, days=180)
        except Exception as e:
            logger.debug(f"Could not get performance history: {e}")
            performance_snapshots = None
        
        # Calculate performance metrics from snapshots
        monthly_performance = None
        quarterly_performance = None
        yearly_performance = None
        
        if performance_snapshots is not None:
            try:
                if hasattr(performance_snapshots, 'exists') and performance_snapshots.exists():
                    snapshots_list = list(performance_snapshots)
                    if snapshots_list:
                        latest = snapshots_list[-1]  # Last item
                        month_ago = timezone.now().date() - timedelta(days=30)
                        quarter_ago = timezone.now().date() - timedelta(days=90)
                        year_ago = timezone.now().date() - timedelta(days=365)
                        
                        month_snapshot = next((s for s in reversed(snapshots_list) if s.snapshot_date <= month_ago), None)
                        quarter_snapshot = next((s for s in reversed(snapshots_list) if s.snapshot_date <= quarter_ago), None)
                        year_snapshot = next((s for s in reversed(snapshots_list) if s.snapshot_date <= year_ago), None)
                        
                        if month_snapshot and latest.total_investment > 0:
                            month_value_change = float(latest.total_value - month_snapshot.total_value)
                            monthly_performance = (month_value_change / float(month_snapshot.total_value)) * 100
                        
                        if quarter_snapshot and latest.total_investment > 0:
                            quarter_value_change = float(latest.total_value - quarter_snapshot.total_value)
                            quarterly_performance = (quarter_value_change / float(quarter_snapshot.total_value)) * 100
                        
                        if year_snapshot and latest.total_investment > 0:
                            year_value_change = float(latest.total_value - year_snapshot.total_value)
                            yearly_performance = (year_value_change / float(year_snapshot.total_value)) * 100
            except Exception as e:
                logger.debug(f"Error processing performance snapshots: {e}")
                performance_snapshots = None
        
        # Performance data for chart - use real snapshot data
        performance_data = []
        if performance_snapshots is not None:
            try:
                if hasattr(performance_snapshots, 'exists') and performance_snapshots.exists():
                    # Get last 6 months of data
                    six_months_ago = timezone.now().date() - timedelta(days=180)
                    recent_snapshots = list(performance_snapshots.filter(snapshot_date__gte=six_months_ago)[:6])
                    
                    if recent_snapshots:
                        base_value = float(recent_snapshots[0].total_value) if recent_snapshots else total_value
                        for snapshot in recent_snapshots:
                            month_name = snapshot.snapshot_date.strftime('%b')
                            if base_value > 0:
                                # Calculate percentage change from base
                                change_percent = ((float(snapshot.total_value) - base_value) / base_value) * 100
                                # Normalize to 0-100 range for visualization
                                normalized = max(0, min(100, 50 + (change_percent * 2)))
                            else:
                                normalized = 50
                            
                            performance_data.append({
                                'month': month_name,
                                'percent': round(normalized, 1),
                                'value': float(snapshot.total_value)
                            })
            except Exception as e:
                logger.debug(f"Error processing performance data: {e}")
                performance_data = []
        
        # If no snapshots, create placeholder data
        if not performance_data and total_value > 0:
            months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
            for month in months:
                performance_data.append({
                    'month': month,
                    'percent': 50.0,
                    'value': total_value
                })
        
        # Calculate dividend income projection
        dividend_projection = PortfolioService.calculate_dividend_projection(portfolio_items, months=12)
        
        # Calculate total projected income and average monthly
        total_projected_income = 0
        if dividend_projection:
            total_projected_income = dividend_projection[-1]['cumulative'] if dividend_projection else 0
        average_monthly_income = total_projected_income / 12 if total_projected_income > 0 else 0
        
        # Create portfolio snapshot for today (if not exists)
        # Only create if PortfolioSnapshot model exists (migration has been run)
        try:
            from portfolio.models import PortfolioSnapshot
            PortfolioService.create_portfolio_snapshot(request.user)
        except (ImportError, Exception) as e:
            # Model doesn't exist yet or other error - skip snapshot creation
            logger.debug(f"Could not create portfolio snapshot (model may not exist yet): {e}")
        
        context = {
            'portfolio_items': portfolio_items,
            'total_value': total_value,
            'total_investment': total_investment,
            'total_gain_loss': total_gain_loss,
            'percent_gain_loss': percent_gain_loss,
            'annual_dividends': annual_dividends,
            'dividend_yield': dividend_yield,
            'total_holdings': total_holdings,
            'sectors_count': sectors_count,
            'upcoming_dividends': upcoming_dividends,
            'watchlist_stocks': watchlist_stocks,
            'upcoming_dividends_count': len(upcoming_dividends),
            'monthly_performance': monthly_performance,
            'quarterly_performance': quarterly_performance,
            'yearly_performance': yearly_performance,
            'performance_data': performance_data,
            'dividend_projection': dividend_projection,  # For projection chart
            'total_projected_income': total_projected_income,  # Total projected income
            'average_monthly_income': average_monthly_income,  # Average monthly income
            'news_items': recent_news,
        }
        
        return render(request, 'dashboard.html', context)
    
    except Exception as e:
        logger.error(f"Error in dashboard view: {e}")
        messages.error(request, 'An error occurred while loading your dashboard.')
        return render(request, 'dashboard.html', {
            'portfolio_items': [],
            'total_value': 0,
            'annual_dividends': 0,
            'total_holdings': 0,
            'upcoming_dividends': [],
            'watchlist_stocks': [],
            'upcoming_dividends_count': 0,
        })

@login_required
@require_http_methods(["GET", "POST"])
def manage_dividend_alerts(request, symbol):
    """Manage dividend alerts for a specific stock with max 5 alerts per user limit"""
    stock = get_object_or_404(Stock, symbol=symbol.upper())
    
    # Check if alert already exists
    alert = DividendAlert.objects.filter(user=request.user, stock=stock).first()
    
    if request.method == 'POST':
        try:
            days_advance = int(request.POST.get('days_advance', 1))
            is_active = request.POST.get('is_active') == 'on'
            
            # Validate days_advance
            if days_advance < 1 or days_advance > 30:
                messages.error(request, 'Days advance must be between 1 and 30.')
                return redirect('manage_dividend_alerts', symbol=symbol)
            
            if alert:
                # Update existing alert
                alert.days_advance = days_advance
                alert.is_active = is_active
                alert.save()
            else:
                # Check if user can add more dividend alerts
                if not AlertService.can_add_dividend_alert(request.user):
                    messages.error(request, f'Maximum limit of {AlertService.MAX_DIVIDEND_ALERTS} dividend alerts reached. Please remove some alerts first.')
                    return redirect('stock_detail', symbol=symbol)
                
                # Create new alert
                alert = DividendAlert.objects.create(
                    user=request.user,
                    stock=stock,
                    days_advance=days_advance,
                    is_active=is_active
                )
            
            status = "enabled" if is_active else "disabled"
            messages.success(request, f'Dividend alerts for {stock.symbol} have been {status}.')
            return redirect('stock_detail', symbol=symbol)
            
        except ValueError:
            messages.error(request, 'Invalid input values. Please check your entries.')
    
    # Get dividend information
    dividend = Dividend.objects.filter(stock=stock).order_by('-ex_dividend_date').first()
    
    context = {
        'stock': stock,
        'dividend': dividend,
        'alert': alert,
        'current_alert_count': DividendAlert.objects.filter(user=request.user).count(),
        'max_alerts': AlertService.MAX_DIVIDEND_ALERTS,
    }
    
    return render(request, 'dividend_alerts.html', context)


@login_required
@require_http_methods(["POST"])
def toggle_dividend_alert(request, symbol):
    """Quick toggle for dividend alerts with max 5 alerts per user limit"""
    stock = get_object_or_404(Stock, symbol=symbol.upper())
    
    # Check if alert already exists
    existing_alert = DividendAlert.objects.filter(user=request.user, stock=stock).first()
    
    if existing_alert:
        # Toggle the alert status
        existing_alert.is_active = not existing_alert.is_active
        existing_alert.save()
        status = "enabled" if existing_alert.is_active else "disabled"
        messages.success(request, f'Dividend alerts for {stock.symbol} have been {status}.')
    else:
        # Check if user can add more dividend alerts
        if not AlertService.can_add_dividend_alert(request.user):
            messages.error(request, f'Maximum limit of {AlertService.MAX_DIVIDEND_ALERTS} dividend alerts reached. Please remove some alerts first.')
        else:
            # Create new alert
            DividendAlert.objects.create(
                user=request.user,
                stock=stock,
                days_advance=1,
                is_active=True
            )
            messages.success(request, f'Dividend alerts for {stock.symbol} have been enabled.')
    
    return redirect('stock_detail', symbol=symbol)

@login_required
def my_alerts(request):
    """View all user's dividend alerts - Optimized with annotations"""
    try:
        # Use service layer for optimized query
        alerts = AlertService.get_alerts_with_annotations(request.user)
        
        # Calculate stats
        active_alerts_count = sum(1 for alert in alerts if alert.is_active)
        upcoming_alerts_count = 0
        today = timezone.now().date()
        
        # Prepare data efficiently
        alerts_data = []
        for alert in alerts:
            latest_dividend = None
            if alert.latest_dividend_amount:
                latest_dividend = type('obj', (object,), {
                    'amount': alert.latest_dividend_amount,
                    'yield_percent': alert.latest_dividend_yield,
                    'ex_dividend_date': alert.latest_dividend_date,
                    'frequency': alert.latest_dividend_frequency or 'N/A',
                })()
                
                # Count upcoming alerts (ex-date in future)
                if alert.latest_dividend_date and alert.latest_dividend_date > today:
                    upcoming_alerts_count += 1
            
            # Calculate days until ex-date
            days_until = None
            if latest_dividend and latest_dividend.ex_dividend_date:
                days_until = (latest_dividend.ex_dividend_date - today).days
            
            alerts_data.append({
                'alert': alert,
                'latest_dividend': latest_dividend,
                'days_until': days_until,
            })
        
        # Sort by days until (upcoming first)
        alerts_data.sort(key=lambda x: x['days_until'] if x['days_until'] is not None and x['days_until'] >= 0 else 999)
        
        context = {
            'alerts': alerts_data,
            'active_alerts_count': active_alerts_count,
            'upcoming_alerts_count': upcoming_alerts_count,
        }
        
        return render(request, 'my_alerts.html', context)
    except Exception as e:
        logger.error(f"Error in my_alerts view: {e}")
        messages.error(request, 'An error occurred while loading your alerts.')
        return redirect('dashboard')        


@csrf_exempt
@require_POST
def trigger_dividend_alerts(request):
    """
    API endpoint to trigger dividend alert emails
    CSRF exempt - uses secret key authentication instead
    """
    # Simple authentication (customize as needed)
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to trigger dividend alerts from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    # Check if dry run is requested
    dry_run = request.POST.get('dry_run', '').lower() == 'true'
    
    try:
        # Run the management command
        call_command('send_dividend_alerts', dry_run=dry_run)
        
        return JsonResponse({
            'status': 'success', 
            'message': 'Dividend alerts processed successfully',
            'dry_run': dry_run
        })
        
    except Exception as e:
        logger.error(f"Error triggering dividend alerts: {e}")
        return JsonResponse({
            'status': 'error', 
            'message': f'Error: {str(e)}'
        }, status=500)

# Global variable to track scraping status
_scraping_status = {
    'is_running': False,
    'started_at': None,
    'completed_at': None,
    'days': None,
    'last_error': None
}

@csrf_exempt
@require_POST
def trigger_daily_scrape(request):
    """
    API endpoint to trigger daily stock scraping
    Runs asynchronously to avoid Render.com timeout issues
    CSRF exempt - uses secret key authentication instead
    """
    import threading
    global _scraping_status
    
    # Simple authentication
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to trigger daily scrape from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    # Check if scraping is already running
    if _scraping_status.get('is_running'):
        return JsonResponse({
            'status': 'busy',
            'message': 'Scraping is already running',
            'started_at': _scraping_status.get('started_at'),
            'days': _scraping_status.get('days')
        }, status=409)
    
    # Get optional parameters
    days = request.POST.get('days', 60)
    
    try:
        # Convert days to integer
        try:
            days = int(days)
            if days < 1 or days > 365:
                days = 60
        except (ValueError, TypeError):
            days = 60
        
        # Run scraping in background thread to avoid timeout
        def run_scrape():
            global _scraping_status
            try:
                _scraping_status['is_running'] = True
                _scraping_status['started_at'] = timezone.now().isoformat()
                _scraping_status['days'] = days
                _scraping_status['last_error'] = None
                _scraping_status['completed_at'] = None
                
                logger.info(f"🚀 Starting background scrape for {days} days at {_scraping_status['started_at']}")
                call_command('daily_scrape', days=days)
                
                _scraping_status['is_running'] = False
                _scraping_status['completed_at'] = timezone.now().isoformat()
                logger.info(f"✅ Background scrape completed for {days} days at {_scraping_status['completed_at']}")
                
            except Exception as e:
                _scraping_status['is_running'] = False
                _scraping_status['last_error'] = str(e)
                _scraping_status['completed_at'] = timezone.now().isoformat()
                logger.error(f"❌ Error in background scrape: {e}")
        
        # Start background thread
        thread = threading.Thread(target=run_scrape, daemon=True)
        thread.start()
        
        # Return immediately to avoid timeout
        return JsonResponse({
            'status': 'accepted', 
            'message': f'Daily stock scrape started in background for {days} days',
            'days': days,
            'started_at': _scraping_status.get('started_at'),
            'note': 'Scraping is running asynchronously. Use /scrape-status/ endpoint to check progress.'
        })
        
    except Exception as e:
        logger.error(f"Error triggering daily scrape: {e}")
        return JsonResponse({
            'status': 'error', 
            'message': f'Error: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
def trigger_newsletter(request):
    """
    API endpoint to trigger newsletter sending
    Runs synchronously (newsletters are usually fast)
    CSRF exempt - uses secret key authentication instead
    """
    import threading
    
    # Simple authentication
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to trigger newsletter from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    # Get optional parameters
    dry_run = request.POST.get('dry_run', '').lower() == 'true'
    
    try:
        # Run newsletter sending in background thread (optional, can be synchronous)
        def run_newsletter():
            try:
                logger.info(f"Starting newsletter sending (dry_run={dry_run})")
                call_command('send_dividend_newsletter', dry_run=dry_run)
                logger.info(f"Newsletter sending completed")
            except Exception as e:
                logger.error(f"Error in newsletter sending: {e}")
        
        # Start background thread
        thread = threading.Thread(target=run_newsletter, daemon=True)
        thread.start()
        
        # Return immediately
        return JsonResponse({
            'status': 'accepted', 
            'message': f'Newsletter sending started in background (dry_run={dry_run})',
            'dry_run': dry_run,
            'note': 'Newsletter is being sent asynchronously. Check logs for progress.'
        })
        
    except Exception as e:
        logger.error(f"Error triggering newsletter: {e}")
        return JsonResponse({
            'status': 'error', 
            'message': f'Error: {str(e)}'
        }, status=500)


@csrf_exempt
def scrape_status(request):
    """
    API endpoint to check scraping status
    No authentication required for status check (or add if needed)
    """
    global _scraping_status
    from portfolio.models import StockPrice
    from django.utils import timezone
    from datetime import timedelta
    
    # Get recent stock price updates (last hour)
    recent_updates = StockPrice.objects.filter(
        price_date=timezone.now().date()
    ).count()
    
    # Get total stocks
    total_stocks = Stock.objects.count()
    
    status_data = {
        'is_running': _scraping_status.get('is_running', False),
        'started_at': _scraping_status.get('started_at'),
        'completed_at': _scraping_status.get('completed_at'),
        'days': _scraping_status.get('days'),
        'last_error': _scraping_status.get('last_error'),
        'database_stats': {
            'total_stocks': total_stocks,
            'stocks_updated_today': recent_updates,
        }
    }
    
    # Calculate duration if running
    if _scraping_status.get('is_running') and _scraping_status.get('started_at'):
        try:
            # Parse ISO format datetime string
            started_str = _scraping_status['started_at']
            started = datetime.fromisoformat(started_str.replace('Z', '+00:00'))
            if started.tzinfo is None:
                started = timezone.make_aware(started)
            duration = (timezone.now() - started).total_seconds()
            status_data['duration_seconds'] = int(duration)
            status_data['duration_minutes'] = round(duration / 60, 1)
        except Exception as e:
            logger.debug(f"Error calculating duration: {e}")
            pass
    
    return JsonResponse(status_data)


@login_required
@require_POST
def delete_dividend_alert(request, alert_id):
    """Delete a dividend alert - supports both AJAX and regular requests"""
    try:
        alert = get_object_or_404(DividendAlert, id=alert_id, user=request.user)
        stock_symbol = alert.stock.symbol
        alert.delete()
        
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': f'Dividend alert for {stock_symbol} has been removed.'
            })
        
        messages.success(request, f'Dividend alert for {stock_symbol} has been removed.')
        return redirect('my_alerts')
        
    except Exception as e:
        logger.error(f"Error deleting dividend alert: {e}")
        
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': 'An error occurred while deleting the alert.'
            }, status=500)
        
        messages.error(request, 'An error occurred while deleting the alert.')
        return redirect('my_alerts')

@login_required
@require_http_methods(["GET", "POST"])
def newsletter_subscription(request):
    """Manage newsletter subscription with preview content"""
    try:
        # Get or create subscription
        subscription, created = NewsletterSubscription.objects.get_or_create(
            user=request.user,
            defaults={'is_active': False, 'frequency': 'weekly'}
        )
        
        if request.method == 'POST':
            if 'subscribe' in request.POST:
                # Subscribe or update preferences
                subscription.is_active = True
                subscription.frequency = request.POST.get('frequency', subscription.frequency or 'weekly')
                
                # Update preferences
                preferences = subscription.preferences or {}
                preferences['strategy'] = request.POST.get('strategy', preferences.get('strategy', 'high_yield'))
                
                # Handle stocks_count safely
                try:
                    stocks_count = int(request.POST.get('stocks_count', preferences.get('stocks_count', 10)))
                    if stocks_count not in [5, 10, 15]:
                        stocks_count = 10
                except (ValueError, TypeError):
                    stocks_count = preferences.get('stocks_count', 10)
                
                preferences['stocks_count'] = stocks_count
                preferences['include_analysis'] = request.POST.get('include_analysis') == 'on'
                subscription.preferences = preferences
                
                subscription.save()
                messages.success(request, 'Newsletter subscription updated successfully!')
                
            elif 'unsubscribe' in request.POST:
                subscription.is_active = False
                subscription.save()
                messages.success(request, 'You have been unsubscribed from the newsletter.')
            
            return redirect('newsletter_subscription')
        
        # Generate preview content using newsletter generator
        generator = DividendNewsletterGenerator()
        
        # Get preview content based on subscription preferences or defaults
        if subscription.is_active and subscription.preferences:
            # Use user's preferences if subscription is active
            preview_content = generator.generate_newsletter_content(user=request.user)
        else:
            # Use defaults for preview
            preview_content = generator.generate_newsletter_content(user=None)
        
        # If no content generated, create empty structure
        if not preview_content or not preview_content.get('top_stocks'):
            preview_content = {
                'top_stocks': [],
                'statistics': {
                    'total_stocks': 0,
                    'average_yield': 0
                },
                'strategy_used': subscription.preferences.get('strategy', 'high_yield') if subscription.preferences else 'high_yield'
            }
        
        context = {
            'subscription': subscription,
            'preview_content': preview_content,
        }
        
        return render(request, 'subscription.html', context)
        
    except Exception as e:
        logger.error(f"Error in newsletter_subscription view: {e}", exc_info=True)
        messages.error(request, 'An error occurred while loading your subscription.')
        return redirect('dashboard')


@login_required
def portfolio_news(request):
    """Display news for stocks in user's portfolio"""
    # Get user's portfolio stocks
    portfolio_stocks = Stock.objects.filter(
        userportfolio__user=request.user
    ).distinct()
    
    # Get recent news (last 7 days)
    cutoff_date = timezone.now() - timedelta(days=7)
    news_items = StockNews.objects.filter(
        stock__in=portfolio_stocks,
        published_at__gte=cutoff_date
    ).select_related('stock').order_by('-published_at')[:50]
    
    # Group by stock
    news_by_stock = {}
    for news in news_items:
        symbol = news.stock.symbol
        if symbol not in news_by_stock:
            news_by_stock[symbol] = {
                'stock': news.stock,
                'articles': []
            }
        news_by_stock[symbol]['articles'].append(news)
    
    context = {
        'news_by_stock': news_by_stock,
        'total_articles': len(news_items),
        'portfolio_stocks_count': portfolio_stocks.count(),
    }
    
    return render(request, 'portfolio_news.html', context)


@login_required
def watchlist_news(request):
    """Display news for stocks in user's watchlist"""
    # Get user's watchlist stocks
    watchlist_stocks = Stock.objects.filter(
        watchlist__user=request.user
    ).distinct()
    
    # Get recent news (last 7 days)
    cutoff_date = timezone.now() - timedelta(days=7)
    news_items = StockNews.objects.filter(
        stock__in=watchlist_stocks,
        published_at__gte=cutoff_date
    ).select_related('stock').order_by('-published_at')[:50]
    
    # Group by stock
    news_by_stock = {}
    for news in news_items:
        symbol = news.stock.symbol
        if symbol not in news_by_stock:
            news_by_stock[symbol] = {
                'stock': news.stock,
                'articles': []
            }
        news_by_stock[symbol]['articles'].append(news)
    
    context = {
        'news_by_stock': news_by_stock,
        'total_articles': len(news_items),
        'watchlist_stocks_count': watchlist_stocks.count(),
    }
    
    return render(request, 'watchlist_news.html', context)


@login_required
def all_news(request):
    """Display all news for portfolio and watchlist stocks combined"""
    # Filter options - determine which stocks to include
    filter_type = request.GET.get('filter', 'all')  # all, portfolio, watchlist
    
    # Optimized: Get stock IDs directly instead of full querysets
    cutoff_date = timezone.now() - timedelta(days=7)
    
    if filter_type == 'portfolio':
        stock_ids = UserPortfolio.objects.filter(user=request.user).values_list('stock_id', flat=True).distinct()
    elif filter_type == 'watchlist':
        stock_ids = Watchlist.objects.filter(user=request.user).values_list('stock_id', flat=True).distinct()
    else:  # 'all'
        # Combine portfolio and watchlist stock IDs efficiently
        portfolio_ids = set(UserPortfolio.objects.filter(user=request.user).values_list('stock_id', flat=True))
        watchlist_ids = set(Watchlist.objects.filter(user=request.user).values_list('stock_id', flat=True))
        stock_ids = list(portfolio_ids | watchlist_ids)
    
    # Get recent news (last 7 days) - optimized query
    if stock_ids:
        news_items = StockNews.objects.filter(
            stock_id__in=stock_ids,
            published_at__gte=cutoff_date
        ).select_related('stock').order_by('-published_at')
    else:
        news_items = StockNews.objects.none()
    
    # Get total count before pagination
    total_articles = news_items.count()
    
    # Get counts for context (optimized)
    portfolio_stocks_count = UserPortfolio.objects.filter(user=request.user).values('stock_id').distinct().count()
    watchlist_stocks_count = Watchlist.objects.filter(user=request.user).values('stock_id').distinct().count()
    
    # Paginate
    paginator = Paginator(news_items, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'news_items': page_obj,
        'filter_type': filter_type,
        'total_articles': total_articles,
        'portfolio_stocks_count': portfolio_stocks_count,
        'watchlist_stocks_count': watchlist_stocks_count,
    }
    
    return render(request, 'all_news.html', context)


@login_required
def stock_news(request, symbol):
    """Display news for a specific stock"""
    stock = get_object_or_404(Stock, symbol=symbol.upper())
    
    # Get recent news (last 30 days)
    cutoff_date = timezone.now() - timedelta(days=30)
    news_items = StockNews.objects.filter(
        stock=stock,
        published_at__gte=cutoff_date
    ).order_by('-published_at')
    
    # Paginate
    paginator = Paginator(news_items, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'stock': stock,
        'news_items': page_obj,
        'total_articles': news_items.count(),
    }
    
    return render(request, 'stock_news.html', context)


@csrf_exempt
@require_POST
def fetch_news(request):
    """
    API endpoint to manually trigger news fetching
    Can be called for specific stocks or all portfolio/watchlist stocks
    """
    # Simple authentication
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to fetch news from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        # Get stocks to fetch news for
        stock_symbols = request.POST.getlist('stocks', [])
        
        if stock_symbols:
            stocks = Stock.objects.filter(symbol__in=[s.upper() for s in stock_symbols])
        else:
            # Fetch for all stocks (can be limited)
            stocks = Stock.objects.all()[:100]  # Limit to prevent timeout
        
        fetcher = NewsFetcher()
        total_saved = fetcher.fetch_and_save_news(stocks, max_articles_per_stock=10)
        
        return JsonResponse({
            'status': 'success',
            'message': f'Fetched and saved {total_saved} news articles',
            'stocks_processed': stocks.count(),
            'articles_saved': total_saved
        })
        
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Error: {str(e)}'
        }, status=500)


def canadian_tools(request):
    """Canadian tax and investment tools page - accessible to all users"""
    context = {
        'provinces': [
            ('ON', 'Ontario'), ('BC', 'British Columbia'), ('AB', 'Alberta'),
            ('QC', 'Quebec'), ('MB', 'Manitoba'), ('SK', 'Saskatchewan'),
            ('NS', 'Nova Scotia'), ('NB', 'New Brunswick'), ('NL', 'Newfoundland'),
            ('PE', 'Prince Edward Island'), ('NT', 'Northwest Territories'),
            ('YT', 'Yukon'), ('NU', 'Nunavut')
        ]
    }
    
    # If form submitted, calculate results
    if request.method == 'POST':
        tool_type = request.POST.get('tool_type')
        
        try:
            if tool_type == 'dividend_tax':
                dividend_amount = float(request.POST.get('dividend_amount', 0) or 0)
                province = request.POST.get('province', 'ON')
                is_eligible = request.POST.get('is_eligible', 'true') == 'true'
                
                if dividend_amount > 0:
                    result = CanadianTaxCalculator.calculate_dividend_tax_credit(
                        dividend_amount, is_eligible, province
                    )
                    context['dividend_result'] = result
                context['tool_type'] = 'dividend_tax'
                
            elif tool_type == 'capital_gains':
                capital_gain = float(request.POST.get('capital_gain', 0) or 0)
                taxable_income = float(request.POST.get('taxable_income', 0) or 0)
                province = request.POST.get('province', 'ON')
                
                if capital_gain > 0:
                    result = CanadianTaxCalculator.calculate_capital_gains_tax(
                        capital_gain, taxable_income, province
                    )
                    context['capital_gains_result'] = result
                context['tool_type'] = 'capital_gains'
                
            elif tool_type == 'rrsp':
                age = int(request.POST.get('age', 30) or 30)
                previous_year_income = float(request.POST.get('previous_year_income', 0) or 0)
                unused_room = float(request.POST.get('unused_room', 0) or 0)
                
                if previous_year_income > 0:
                    result = CanadianTaxCalculator.calculate_rrsp_contribution_limit(
                        age, previous_year_income, unused_room
                    )
                    context['rrsp_result'] = result
                context['tool_type'] = 'rrsp'
                
            elif tool_type == 'tfsa':
                age = int(request.POST.get('age', 18) or 18)
                year = int(request.POST.get('year', 2024) or 2024)
                previous_contributions = float(request.POST.get('previous_contributions', 0) or 0)
                
                result = CanadianTaxCalculator.calculate_tfsa_contribution_limit(
                    age, year, previous_contributions
                )
                context['tfsa_result'] = result
                context['tool_type'] = 'tfsa'
                
            elif tool_type == 'portfolio_tax' and request.user.is_authenticated:
                # Get user's portfolio data
                portfolio_items = PortfolioService.get_portfolio_with_annotations(request.user)
                annual_income = float(request.POST.get('annual_income', 0) or 0)
                province = request.POST.get('province', 'ON')
                
                # Prepare portfolio data
                portfolio_data = []
                for item in portfolio_items:
                    annual_dividends = PortfolioService.calculate_annual_dividend(
                        item.latest_dividend_amount,
                        item.shares_owned,
                        item.latest_dividend_frequency
                    )
                    
                    # Calculate capital gains
                    current_value = 0
                    investment_value = 0
                    if item.latest_price_value and item.shares_owned:
                        current_value = float(item.latest_price_value * item.shares_owned)
                    if item.average_cost and item.shares_owned:
                        investment_value = float(item.average_cost * item.shares_owned)
                    
                    capital_gains = max(0, current_value - investment_value)
                    
                    portfolio_data.append({
                        'symbol': item.stock.symbol,
                        'annual_dividends': annual_dividends,
                        'capital_gains': capital_gains
                    })
                
                if portfolio_data:
                    result = CanadianTaxCalculator.calculate_portfolio_tax_summary(
                        portfolio_data, annual_income, province
                    )
                    context['portfolio_tax_result'] = result
                context['tool_type'] = 'portfolio_tax'
                context['portfolio_items'] = portfolio_data
            else:
                context['tool_type'] = tool_type
                
        except (ValueError, TypeError) as e:
            logger.error(f"Error processing tax tool calculation: {e}")
            messages.error(request, f"Invalid input. Please check your values and try again.")
            context['tool_type'] = tool_type
        except Exception as e:
            logger.error(f"Unexpected error in tax tool: {e}")
            messages.error(request, "An error occurred. Please try again.")
            context['tool_type'] = tool_type
    
    return render(request, 'canadian_tools.html', context)