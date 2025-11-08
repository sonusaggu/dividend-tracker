from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, F, Case, When, Value, IntegerField, Subquery, OuterRef, Exists
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.db import DatabaseError
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.management import call_command
import subprocess
from django.conf import settings
import logging

from .forms import RegistrationForm
from .models import Stock, Dividend, StockPrice, ValuationMetric, AnalystRating
from .models import UserPortfolio, UserAlert, Watchlist, DividendAlert

# Set up logging
logger = logging.getLogger(__name__)

def login_view(request):
    """User login view with CSRF protection"""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        if not username or not password:
            messages.error(request, 'Username and password are required.')
            return render(request, 'login.html')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Redirect to next page if provided, otherwise to dashboard
            next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard'
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
            # Don't reveal whether username exists
            logger.warning(f"Failed login attempt for username: {username}")
    
    return render(request, 'login.html')

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
        thirty_days_later = today + timedelta(days=30)
        
        # Single optimized query using subqueries to avoid N+1
        dividends_with_data = Dividend.objects.filter(
            ex_dividend_date__gte=today,
            ex_dividend_date__lte=thirty_days_later
        ).select_related('stock').annotate(
            # Get latest price in the same query using subquery
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
        ).order_by('ex_dividend_date')[:12]
        
        # Prepare data efficiently
        upcoming_dividends = []
        for dividend in dividends_with_data:
            upcoming_dividends.append({
                'symbol': dividend.stock.symbol,
                'company_name': dividend.stock.company_name,
                'last_price': dividend.latest_price or 'N/A',
                'dividend_amount': dividend.amount,
                'dividend_yield': dividend.yield_percent,
                'ex_dividend_date': dividend.ex_dividend_date,
                'days_until': (dividend.ex_dividend_date - today).days,
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

    # --- 3️⃣ Base queryset
    stocks = Stock.objects.all()

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

    # --- 5️⃣ Prepare subqueries
    latest_dividends = Dividend.objects.filter(stock=OuterRef('pk')).order_by('-ex_dividend_date')
    upcoming_dividends = Dividend.objects.filter(
        stock=OuterRef('pk'),
        ex_dividend_date__gte=timezone.now().date()
    ).order_by('ex_dividend_date')
    latest_prices = StockPrice.objects.filter(stock=OuterRef('pk')).order_by('-price_date')
    stocks = stocks.annotate(
    latest_price_value=Subquery(latest_prices.values('last_price')[:1]),
    latest_price_date=Subquery(latest_prices.values('price_date')[:1]),
    )

    # --- 6️⃣ Annotate all required fields (no N+1 queries)
    stocks = stocks.annotate(
        latest_dividend_amount=Subquery(latest_dividends.values('amount')[:1]),
        latest_dividend_yield=Subquery(latest_dividends.values('yield_percent')[:1]),
        latest_dividend_date=Subquery(latest_dividends.values('ex_dividend_date')[:1]),
        latest_dividend_frequency=Subquery(latest_dividends.values('frequency')[:1]),
        upcoming_dividend_date=Subquery(upcoming_dividends.values('ex_dividend_date')[:1]),
        latest_price_value=Subquery(latest_prices.values('last_price')[:1]),
        latest_price_date=Subquery(latest_prices.values('price_date')[:1]),
        has_dividend=Exists(Dividend.objects.filter(stock=OuterRef('pk')))
    )

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
    """Detailed view for a single stock"""
    # Validate symbol format
    if not symbol or not isinstance(symbol, str) or len(symbol) > 10:
        raise HttpResponseBadRequest("Invalid stock symbol")
    
    stock = get_object_or_404(Stock, symbol=symbol.upper())
    
    # Get latest data
    latest_price = StockPrice.objects.filter(stock=stock).order_by('-price_date').first()
    dividend = Dividend.objects.filter(stock=stock).order_by('-ex_dividend_date').first()
    valuation = ValuationMetric.objects.filter(stock=stock).order_by('-metric_date').first()
    analyst_rating = AnalystRating.objects.filter(stock=stock).order_by('-rating_date').first()
    
    # Check if stock is in user's watchlist and portfolio
    in_watchlist = False
    in_portfolio = False
    has_dividend_alert = False
    portfolio_item = None
    
    if request.user.is_authenticated:
        in_watchlist = Watchlist.objects.filter(user=request.user, stock=stock).exists()
        portfolio_item = UserPortfolio.objects.filter(user=request.user, stock=stock).first()
        in_portfolio = portfolio_item is not None
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
    }
    
    return render(request, 'stock_detail.html', context)

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
            # Check if user has reached the maximum limit
            current_count = Watchlist.objects.filter(user=request.user).count()
            if current_count >= 10:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Maximum limit of 10 watchlist stocks reached. Please remove some stocks first.'
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
    """View user's watchlist"""
    try:
        watchlist_items = Watchlist.objects.filter(user=request.user).select_related('stock')
        
        # Get latest prices and dividends for watchlist items
        watchlist_data = []
        for item in watchlist_items:
            latest_price = StockPrice.objects.filter(stock=item.stock).order_by('-price_date').first()
            latest_dividend = Dividend.objects.filter(stock=item.stock).order_by('-created_at').first()
            in_portfolio = UserPortfolio.objects.filter(user=request.user, stock=item.stock).exists()
            
            watchlist_data.append({
                'stock': item.stock,
                'latest_price': latest_price,
                'latest_dividend': latest_dividend,
                'in_portfolio': in_portfolio,
                'watchlist_item': item
            })
        
        # Calculate stats for the template
        dividend_stocks_count = sum(1 for item in watchlist_data if item['latest_dividend'])
        sectors = set(item['stock'].sector for item in watchlist_data if item['stock'].sector)
        
        return render(request, 'watchlist.html', {
            'watchlist_items': watchlist_data,
            'dividend_stocks_count': dividend_stocks_count,
            'sectors_count': len(sectors),
            'watchlist_count': len(watchlist_items),  # Add this line
        })
    
    except Exception as e:
        logger.error(f"Error in watchlist_view: {e}")
        messages.error(request, 'An error occurred while loading your watchlist.')
        return redirect('dashboard')

@login_required
def portfolio_view(request):
    """View user's portfolio"""
    try:
        portfolio_items = UserPortfolio.objects.filter(user=request.user).select_related('stock')
        
        # Calculate portfolio statistics
        total_value = 0
        total_investment = 0
        annual_dividend_income = 0
        
        portfolio_data = []
        for item in portfolio_items:
            latest_price = StockPrice.objects.filter(stock=item.stock).order_by('-price_date').first()
            latest_dividend = Dividend.objects.filter(stock=item.stock).order_by('-created_at').first()
            
            # Calculate current value and gains
            current_value = item.shares_owned * latest_price.last_price if latest_price and item.shares_owned else 0
            investment_value = item.shares_owned * item.average_cost if item.average_cost and item.shares_owned else 0
            gain_loss = current_value - investment_value if investment_value else 0
            
            # Calculate dividend income
            if latest_dividend and item.shares_owned > 0:
                if latest_dividend.frequency == 'Monthly':
                    dividend_income = latest_dividend.amount * item.shares_owned * 12
                elif latest_dividend.frequency == 'Quarterly':
                    dividend_income = latest_dividend.amount * item.shares_owned * 4
                elif latest_dividend.frequency == 'Semi-Annual':
                    dividend_income = latest_dividend.amount * item.shares_owned * 2
                elif latest_dividend.frequency == 'Annual':
                    dividend_income = latest_dividend.amount * item.shares_owned
                else:
                    dividend_income = 0
            else:
                dividend_income = 0
            
            portfolio_data.append({
                'item': item,
                'current_value': current_value,
                'investment_value': investment_value,
                'gain_loss': gain_loss,
                'dividend_income': dividend_income,
                'latest_price': latest_price,
                'latest_dividend': latest_dividend
            })
            
            total_value += current_value
            total_investment += investment_value
            annual_dividend_income += dividend_income
        
        total_gain_loss = total_value - total_investment
        
        return render(request, 'portfolio.html', {
            'portfolio_items': portfolio_data,
            'total_value': total_value,
            'total_investment': total_investment,
            'total_gain_loss': total_gain_loss,
            'annual_dividend_income': annual_dividend_income
        })
    
    except Exception as e:
        logger.error(f"Error in portfolio_view: {e}")
        messages.error(request, 'An error occurred while loading your portfolio.')
        return redirect('dashboard')

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
            
            # Check if user has reached the maximum limit for dividend alerts
            dividend_alerts_count = UserAlert.objects.filter(
                user=request.user, 
                alert_type='dividend'
            ).count()
            
            if dividend_alerts_count >= 5:
                messages.error(request, 'Maximum limit of 5 dividend alerts reached. Please remove some alerts first.')
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
    """User dashboard with portfolio overview"""
    try:
        # Get user's portfolio items
        portfolio_items = UserPortfolio.objects.filter(user=request.user).select_related('stock')
        
        # Calculate portfolio metrics
        total_value = 0
        annual_dividends = 0
        total_holdings = portfolio_items.count()
        
        for item in portfolio_items:
            # Get latest price
            latest_price = StockPrice.objects.filter(stock=item.stock).order_by('-price_date').first()
            if latest_price and item.shares_owned:
                item.current_value = latest_price.last_price * item.shares_owned
                total_value += item.current_value
            
            # Get dividend information
            dividend = Dividend.objects.filter(stock=item.stock).order_by('-ex_dividend_date').first()
            if dividend and dividend.amount and item.shares_owned:
                item_dividend = dividend.amount * item.shares_owned
                # Adjust for frequency
                if dividend.frequency == 'Quarterly':
                    item_dividend *= 4
                elif dividend.frequency == 'Semi-Annual':
                    item_dividend *= 2
                annual_dividends += item_dividend
        
        # Get upcoming dividends for user's stocks
        upcoming_dividends = []
        thirty_days_later = timezone.now().date() + timedelta(days=30)
        
        user_dividends = Dividend.objects.filter(
            stock__userportfolio__user=request.user,
            ex_dividend_date__gte=timezone.now().date(),
            ex_dividend_date__lte=thirty_days_later
        ).select_related('stock').order_by('ex_dividend_date')
        
        for dividend in user_dividends:
            days_until = (dividend.ex_dividend_date - timezone.now().date()).days
            upcoming_dividends.append({
                'stock': dividend.stock,
                'amount': dividend.amount,
                'ex_dividend_date': dividend.ex_dividend_date,
                'days_until': days_until
            })
        
        # Get watchlist stocks
        watchlist_items = Watchlist.objects.filter(user=request.user).select_related('stock')[:5]
        watchlist_stocks = [item.stock for item in watchlist_items]
        
        # Add mock price changes for demo (consider removing this in production)
        for stock in watchlist_stocks:
            stock.change = round((timezone.now().microsecond % 200 - 100) / 100, 2)
        
        context = {
            'portfolio_items': portfolio_items,
            'total_value': total_value,
            'annual_dividends': annual_dividends,
            'total_holdings': total_holdings,
            'upcoming_dividends': upcoming_dividends[:3],  # Only show next 3
            'watchlist_stocks': watchlist_stocks,
            'upcoming_dividends_count': len(upcoming_dividends),
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
                # Check if user has reached the maximum limit
                current_count = DividendAlert.objects.filter(user=request.user).count()
                if current_count >= 5:
                    messages.error(request, 'Maximum limit of 5 dividend alerts reached. Please remove some alerts first.')
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
        'max_alerts': 5,
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
        # Check if user has reached the maximum limit
        current_count = DividendAlert.objects.filter(user=request.user).count()
        if current_count >= 5:
            messages.error(request, 'Maximum limit of 5 dividend alerts reached. Please remove some alerts first.')
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
    """View all user's dividend alerts"""
    alerts = DividendAlert.objects.filter(user=request.user).select_related('stock')
    
    # Get latest dividend info for each stock
    alerts_data = []
    for alert in alerts:
        latest_dividend = Dividend.objects.filter(
            stock=alert.stock
        ).order_by('-ex_dividend_date').first()
        
        alerts_data.append({
            'alert': alert,
            'latest_dividend': latest_dividend,
        })
    
    context = {
        'alerts': alerts_data,
    }
    
    return render(request, 'my_alerts.html', context)        


@csrf_exempt
@require_POST
def trigger_dividend_alerts(request):
    """
    API endpoint to trigger dividend alert emails
    """
    # Simple authentication (customize as needed)
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', 'your-secret-key-here'):
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

@csrf_exempt
@require_POST
def trigger_daily_scrape(request):
    """
    API endpoint to trigger daily stock scraping
    """
    # Simple authentication
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', 'your-scrape-secret-key-here'):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    # Get optional parameters
    days = request.POST.get('days', 60)
    
    try:
        # Convert days to integer
        try:
            days = int(days)
        except ValueError:
            days = 60
        
        # Run the management command
        call_command('daily_scrape')
        
        return JsonResponse({
            'status': 'success', 
            'message': f'Daily stock scrape completed for {days} days',
            'days': days
        })
        
    except Exception as e:
        logger.error(f"Error triggering daily scrape: {e}")
        return JsonResponse({
            'status': 'error', 
            'message': f'Error: {str(e)}'
        }, status=500)


@login_required
@require_POST
def delete_dividend_alert(request, alert_id):
    """Delete a dividend alert"""
    try:
        alert = get_object_or_404(DividendAlert, id=alert_id, user=request.user)
        stock_symbol = alert.stock.symbol
        alert.delete()
        
        messages.success(request, f'Dividend alert for {stock_symbol} has been removed.')
        return redirect('my_alerts')
        
    except Exception as e:
        logger.error(f"Error deleting dividend alert: {e}")
        messages.error(request, 'An error occurred while deleting the alert.')
        return redirect('my_alerts')