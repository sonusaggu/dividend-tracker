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
from django.db.utils import ProgrammingError, OperationalError
from django.conf import settings
from django.views.decorators.cache import cache_control
from datetime import datetime, timedelta, date
from django.core.management import call_command
import subprocess
import logging
import os
import re

from .forms import RegistrationForm
from .models import Stock, Dividend, StockPrice, ValuationMetric, AnalystRating
from .models import UserPortfolio, UserAlert, Watchlist, DividendAlert, NewsletterSubscription, StockNews, StockNote, Transaction
from .services import PortfolioService, StockService, AlertService, TransactionService
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
            # Check if email is verified - REQUIRED for login
            email_verified = True  # Default to True for graceful degradation
            try:
                from portfolio.models import EmailVerification
                from django.db import connection
                
                # Check if table exists (works for both PostgreSQL and SQLite)
                table_name = EmailVerification._meta.db_table
                table_exists = False
                
                try:
                    if connection.vendor == 'postgresql':
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                                [table_name]
                            )
                            table_exists = cursor.fetchone()[0]
                    elif connection.vendor == 'sqlite':
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                                [table_name]
                            )
                            table_exists = cursor.fetchone() is not None
                    else:
                        # For other databases, try to query the table
                        EmailVerification.objects.first()
                        table_exists = True
                except Exception:
                    table_exists = False
                
                if table_exists:
                    try:
                        verification = EmailVerification.objects.get(user=user)
                        email_verified = verification.is_verified
                        if not email_verified:
                            # Block login if email is not verified
                            messages.error(
                                request,
                                f'Your email address ({user.email}) is not yet verified. Please check your inbox for the verification email and click the verification link before logging in.'
                            )
                            logger.warning(f"Login blocked for user {user.username} - email not verified")
                            # Show resend verification option
                            context = {
                                'next': request.POST.get('next') or request.GET.get('next'),
                                'unverified_email': user.email,
                                'username': username,
                            }
                            return render(request, 'login.html', context)
                    except EmailVerification.DoesNotExist:
                        # If no verification record exists, check if user is old (created before verification was required)
                        # For new users, require verification. For old users, allow login but create verification record
                        from django.utils import timezone
                        from datetime import timedelta
                        # If user was created more than 7 days ago, consider them legacy and allow login
                        if user.date_joined < timezone.now() - timedelta(days=7):
                            logger.info(f"Legacy user {user.username} logged in without EmailVerification record")
                            email_verified = True
                        else:
                            # New user without verification - block login
                            messages.error(
                                request,
                                f'Your email address ({user.email}) is not yet verified. Please check your inbox for the verification email and click the verification link before logging in.'
                            )
                            logger.warning(f"Login blocked for new user {user.username} - no verification record")
                            context = {
                                'next': request.POST.get('next') or request.GET.get('next'),
                                'unverified_email': user.email,
                                'username': username,
                            }
                            return render(request, 'login.html', context)
            except Exception as e:
                # If table doesn't exist or any error, allow login (graceful degradation)
                logger.debug(f"Email verification check skipped: {e}")
                email_verified = True
            
            # Only login if email is verified
            if not email_verified:
                context = {
                    'next': request.POST.get('next') or request.GET.get('next'),
                    'unverified_email': user.email,
                    'username': username,
                }
                return render(request, 'login.html', context)
            
            login(request, user)
            
            # Handle "Remember Me" - set session expiry
            remember_me = request.POST.get('remember-me')
            if remember_me == 'on':  # Checkbox returns 'on' when checked
                # Set session to expire in 30 days
                request.session.set_expiry(2592000)  # 30 days in seconds
                # Also set persistent cookie
                request.session.setdefault('remember_me', True)
            else:
                # Default session expiry (when browser closes)
                request.session.set_expiry(0)
                request.session.pop('remember_me', None)
            
            # Redirect to next page if provided, otherwise to dashboard
            next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard'
            # Validate next URL to prevent open redirects using Django's utility
            from django.utils.http import is_safe_url
            if not is_safe_url(next_url, allowed_hosts={request.get_host()}):
                next_url = 'dashboard'
                # For now, default to dashboard if it doesn't start with /
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
    """User registration view with CSRF protection and email verification"""
    # If user is already authenticated, redirect to dashboard
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                # Email validation is now handled in the form's clean_email method
                # Additional checks are done there (format, domain, disposable, etc.)
                # Username is auto-generated if not provided
                user = form.save()
                
                # Create email verification token
                email_sent = False
                try:
                    from portfolio.utils.email_verification import create_verification_token, send_verification_email
                    from portfolio.models import EmailVerification
                    from django.db import connection
                    
                    # Check if EmailVerification table exists (works for both PostgreSQL and SQLite)
                    table_name = EmailVerification._meta.db_table
                    table_exists = False
                    
                    try:
                        if connection.vendor == 'postgresql':
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                                    [table_name]
                                )
                                table_exists = cursor.fetchone()[0]
                        elif connection.vendor == 'sqlite':
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                                    [table_name]
                                )
                                table_exists = cursor.fetchone() is not None
                        else:
                            # For other databases, try to query the table
                            EmailVerification.objects.first()
                            table_exists = True
                    except Exception as e:
                        logger.warning(f"Could not check if EmailVerification table exists: {e}")
                        table_exists = False
                    
                    if table_exists:
                        verification = create_verification_token(user)
                        email_sent = send_verification_email(user, verification.token)
                        if email_sent:
                            logger.info(f"Verification email sent successfully to {user.email}")
                        else:
                            logger.error(f"Failed to send verification email to {user.email}")
                    else:
                        email_sent = False
                        logger.warning("EmailVerification table doesn't exist yet. Skipping email verification.")
                except Exception as e:
                    logger.error(f"Error creating verification token for {user.email}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    email_sent = False
                
                if email_sent:
                    messages.success(
                        request, 
                        f'Registration successful! Please check your email ({user.email}) to verify your account. You can log in after verification.'
                    )
                else:
                    error_msg = f'Account created, but we couldn\'t send the verification email to {user.email}. Please check email configuration or contact support.'
                    messages.warning(request, error_msg)
                    logger.error(f"Registration succeeded but email sending failed for {user.email}")
                
                # Don't auto-login - user must verify email first
                return redirect('verify_email_sent')
            except Exception as e:
                logger.error(f"Error during user registration: {e}")
                messages.error(request, 'An error occurred during registration. Please try again.')
        else:
            # Log form errors for debugging (not shown to user)
            logger.debug(f"Registration form errors: {form.errors}")
            # Show user-friendly error messages
            if 'username' in form.errors:
                for error in form.errors['username']:
                    if 'already exists' in str(error).lower():
                        messages.error(request, 'This username is already taken. Please choose another.')
    else:
        # Pre-fill email if provided in URL parameter
        initial_data = {}
        email = request.GET.get('email', '').strip()
        if email:
            initial_data['email'] = email
        form = RegistrationForm(initial=initial_data)
    
    return render(request, 'register.html', {'form': form})

def logout_view(request):
    """User logout view"""
    logout(request)
    return redirect('home')


def demo_mode(request):
    """Demo mode - let users explore without registering"""
    # Create demo context with sample data
    from portfolio.models import Stock, StockPrice, Dividend
    from django.db.models import Q
    
    # Get some sample stocks for demo
    demo_stocks = Stock.objects.filter(
        Q(symbol__in=['RY', 'TD', 'BNS', 'ENB', 'TRP', 'CM']) |
        Q(tsx60_member=True)
    )[:6].select_related()
    
    # Get prices for demo stocks
    demo_data = []
    for stock in demo_stocks:
        latest_price = StockPrice.objects.filter(stock=stock).order_by('-price_date').first()
        latest_dividend = Dividend.objects.filter(stock=stock).order_by('-ex_dividend_date').first()
        
        demo_data.append({
            'stock': stock,
            'price': latest_price.last_price if latest_price else None,
            'dividend': latest_dividend.amount if latest_dividend else None,
            'yield': latest_dividend.yield_percent if latest_dividend else None,
        })
    
    # Sample portfolio value for demo
    demo_portfolio_value = 125000.00
    demo_annual_dividends = 4500.00
    demo_monthly_dividends = demo_annual_dividends / 12
    
    context = {
        'demo_stocks': demo_data,
        'demo_portfolio_value': demo_portfolio_value,
        'demo_annual_dividends': demo_annual_dividends,
        'demo_monthly_dividends': demo_monthly_dividends,
        'is_demo': True,
    }
    
    return render(request, 'demo_mode.html', context)


def google_oauth_login(request):
    """Initiate Google OAuth login (works for both registration and login)"""
    from portfolio.utils.google_oauth import get_google_oauth_url
    import os
    from decouple import config
    
    # Build redirect URI - ALWAYS use Render hostname in production (even if custom domain is used)
    render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    redirect_uri = None
    
    # Priority: 1. Explicit env var, 2. Render hostname (ALWAYS in production), 3. Request URI (localhost only)
    explicit_redirect = config('GOOGLE_OAUTH_REDIRECT_URI', default='')
    if explicit_redirect:
        redirect_uri = explicit_redirect
        logger.info(f"Using explicit GOOGLE_OAUTH_REDIRECT_URI: {redirect_uri}")
    elif render_hostname:
        # ALWAYS use Render hostname in production, even if request comes from custom domain
        redirect_uri = f"https://{render_hostname}/auth/google/callback/"
        logger.info(f"✅ Using Render hostname for OAuth (ignoring custom domain): {redirect_uri}")
        logger.info(f"   Request came from: {request.get_host()}, but using Render hostname for OAuth")
    else:
        # Only use request URI for localhost development
        redirect_uri = request.build_absolute_uri('/auth/google/callback/')
        logger.info(f"Using request URI for redirect (localhost): {redirect_uri}")
    
    # Log for debugging
    logger.info(f"🔍 OAuth Debug Info:")
    logger.info(f"   - RENDER_EXTERNAL_HOSTNAME: {render_hostname}")
    logger.info(f"   - Request host: {request.get_host()}")
    logger.info(f"   - Request scheme: {request.scheme}")
    logger.info(f"   - Request port: {request.get_port()}")
    logger.info(f"   - Final redirect URI: {redirect_uri}")
    
    # Get Google OAuth URL
    auth_url = get_google_oauth_url(request, redirect_uri)
    
    if not auth_url:
        messages.error(request, 'Google OAuth is not configured. Please contact support.')
        # Redirect to login if user is trying to login, otherwise to register
        if request.user.is_authenticated:
            return redirect('dashboard')
        return redirect('login')
    
    # Store redirect_uri in session for callback
    request.session['google_oauth_redirect_uri'] = redirect_uri
    
    # Store where user came from (login or register) for better UX
    referer = request.META.get('HTTP_REFERER', '')
    if 'register' in referer:
        request.session['oauth_source'] = 'register'
    else:
        request.session['oauth_source'] = 'login'
    
    # Redirect to Google
    return redirect(auth_url)


def google_oauth_callback(request):
    """Handle Google OAuth callback"""
    from portfolio.utils.google_oauth import (
        exchange_code_for_token,
        get_user_info,
        create_or_get_user
    )
    from django.contrib.auth import login as django_login
    
    # Get authorization code from query parameters
    code = request.GET.get('code')
    error = request.GET.get('error')
    
    if error:
        logger.error(f"Google OAuth error: {error}")
        messages.error(request, 'Google authentication was cancelled or failed.')
        # Redirect based on where they came from
        oauth_source = request.session.get('oauth_source', 'register')
        return redirect('register' if oauth_source == 'register' else 'login')
    
    if not code:
        messages.error(request, 'No authorization code received from Google.')
        # Redirect based on where they came from
        oauth_source = request.session.get('oauth_source', 'register')
        return redirect('register' if oauth_source == 'register' else 'login')
    
    # Get redirect URI from session (must match the one used in auth URL)
    redirect_uri = request.session.get('google_oauth_redirect_uri')
    if not redirect_uri:
        # Fallback to building from request - ALWAYS use Render hostname in production
        import os
        from decouple import config
        render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
        explicit_redirect = config('GOOGLE_OAUTH_REDIRECT_URI', default='')
        
        if explicit_redirect:
            redirect_uri = explicit_redirect
        elif render_hostname:
            # ALWAYS use Render hostname, even if request came from custom domain
            redirect_uri = f"https://{render_hostname}/auth/google/callback/"
            logger.info(f"Callback: Using Render hostname (ignoring custom domain): {redirect_uri}")
        else:
            redirect_uri = request.build_absolute_uri('/auth/google/callback/')
    
    # Clean up session
    if 'google_oauth_redirect_uri' in request.session:
        del request.session['google_oauth_redirect_uri']
    
    # Exchange code for access token
    token_response = exchange_code_for_token(code, redirect_uri)
    
    if not token_response or 'access_token' not in token_response:
        logger.error("Failed to exchange code for token")
        messages.error(request, 'Failed to authenticate with Google. Please try again.')
        oauth_source = request.session.get('oauth_source', 'register')
        return redirect('register' if oauth_source == 'register' else 'login')
    
    access_token = token_response['access_token']
    
    # Get user info from Google
    user_info = get_user_info(access_token)
    
    if not user_info:
        logger.error("Failed to get user info from Google")
        messages.error(request, 'Failed to get user information from Google. Please try again.')
        oauth_source = request.session.get('oauth_source', 'register')
        return redirect('register' if oauth_source == 'register' else 'login')
    
    # Validate email domain (same as registration form)
    email = user_info.get('email', '').lower().strip()
    if email:
        from portfolio.utils.email_validator import validate_email_domain
        is_valid, error = validate_email_domain(email)
        if not is_valid:
            messages.error(request, f'Email validation failed: {error}')
            oauth_source = request.session.get('oauth_source', 'register')
            return redirect('register' if oauth_source == 'register' else 'login')
    
    # Check if this is a new user or existing user BEFORE creating/getting
    from django.contrib.auth.models import User
    is_new_user = not User.objects.filter(email=email).exists()
    
    # Create or get user
    user = create_or_get_user(user_info)
    
    if not user:
        messages.error(request, 'Failed to create or retrieve user account.')
        # Redirect based on where they came from
        oauth_source = request.session.get('oauth_source', 'register')
        return redirect('register' if oauth_source == 'register' else 'login')
    
    # Log the user in
    django_login(request, user)
    
    # Success message - different for new vs existing users
    oauth_source = request.session.get('oauth_source', 'login')  # Default to login
    if is_new_user:
        messages.success(request, f'🎉 Welcome to StockFolio! Your account has been created and you\'re logged in as {user.email}')
    else:
        messages.success(request, f'Welcome back! You\'ve been logged in as {user.email}')
    
    # Clean up session
    if 'oauth_source' in request.session:
        del request.session['oauth_source']
    
    # Redirect to dashboard
    return redirect('dashboard')


def google_oauth_debug(request):
    """Debug view to show current OAuth configuration"""
    import os
    from decouple import config
    
    render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    explicit_redirect = config('GOOGLE_OAUTH_REDIRECT_URI', default='')
    client_id = config('GOOGLE_OAUTH_CLIENT_ID', default='')
    has_client_secret = bool(config('GOOGLE_OAUTH_CLIENT_SECRET', default=''))
    
    # Determine what redirect URI would be used (same logic as google_oauth_login)
    if explicit_redirect:
        redirect_uri = explicit_redirect
        source = "GOOGLE_OAUTH_REDIRECT_URI env var"
    elif render_hostname:
        # ALWAYS use Render hostname in production, even if request comes from custom domain
        redirect_uri = f"https://{render_hostname}/auth/google/callback/"
        source = f"RENDER_EXTERNAL_HOSTNAME (ignoring custom domain: {request.get_host()})"
    else:
        redirect_uri = request.build_absolute_uri('/auth/google/callback/')
        source = "Request URI (fallback - localhost only)"
    
    # Check if custom domain is being used
    request_host = request.get_host()
    using_custom_domain = render_hostname and request_host != render_hostname and 'onrender.com' not in request_host
    
    context = {
        'client_id_configured': bool(client_id),
        'client_secret_configured': has_client_secret,
        'redirect_uri': redirect_uri,
        'redirect_uri_source': source,
        'render_hostname': render_hostname,
        'request_host': request_host,
        'request_scheme': request.scheme,
        'explicit_redirect': explicit_redirect,
        'using_custom_domain': using_custom_domain,
        'should_use_render_hostname': bool(render_hostname),
    }
    
    return render(request, 'google_oauth_debug.html', context)


def verify_email(request, token):
    """Verify user email with token"""
    from portfolio.models import EmailVerification
    from portfolio.utils.email_verification import create_verification_token, send_verification_email
    from django.db import connection
    
    try:
        # Check if table exists (works for both PostgreSQL and SQLite)
        table_name = EmailVerification._meta.db_table
        table_exists = False
        
        try:
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                        [table_name]
                    )
                    table_exists = cursor.fetchone()[0]
            elif connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        [table_name]
                    )
                    table_exists = cursor.fetchone() is not None
            else:
                # For other databases, try to query the table
                EmailVerification.objects.first()
                table_exists = True
        except Exception:
            table_exists = False
        
        if not table_exists:
            messages.error(request, 'Email verification is not yet available. Please run migrations.')
            return redirect('login')
        
        verification = EmailVerification.objects.get(token=token, is_verified=False)
        
        # Check if token is expired
        if verification.is_expired():
            # Generate new token and send new email
            new_verification = create_verification_token(verification.user)
            send_verification_email(verification.user, new_verification.token)
            messages.error(
                request,
                'This verification link has expired. A new verification email has been sent to your inbox.'
            )
            return redirect('verify_email_sent')
        
        # Verify the email
        verification.is_verified = True
        verification.verified_at = timezone.now()
        verification.save()
        
        messages.success(request, 'Email verified successfully! You can now log in to your account.')
        return redirect('login')
        
    except EmailVerification.DoesNotExist:
        messages.error(request, 'Invalid or already used verification link.')
        return redirect('login')
    except Exception as e:
        logger.error(f"Error verifying email: {e}")
        messages.error(request, 'An error occurred during verification. Please try again.')
        return redirect('login')


def verify_email_sent(request):
    """Show page after registration or when verification email is sent"""
    return render(request, 'verify_email_sent.html')


@login_required
def resend_verification_email(request):
    """Resend verification email to logged-in user"""
    from portfolio.models import EmailVerification
    from portfolio.utils.email_verification import create_verification_token, send_verification_email
    from django.db import connection
    
    try:
        # Check if table exists (works for both PostgreSQL and SQLite)
        table_name = EmailVerification._meta.db_table
        table_exists = False
        
        try:
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                        [table_name]
                    )
                    table_exists = cursor.fetchone()[0]
            elif connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        [table_name]
                    )
                    table_exists = cursor.fetchone() is not None
            else:
                # For other databases, try to query the table
                EmailVerification.objects.first()
                table_exists = True
        except Exception:
            table_exists = False
        
        if not table_exists:
            messages.error(request, 'Email verification is not yet available. Please run migrations.')
            return redirect('dashboard')
        
        # Get or create verification record
        verification, created = EmailVerification.objects.get_or_create(
            user=request.user,
            defaults={'is_verified': False}
        )
        
        if verification.is_verified:
            messages.info(request, 'Your email is already verified.')
            return redirect('dashboard')
        
        # Generate new token
        verification = create_verification_token(request.user)
        
        # Send email
        email_sent = send_verification_email(request.user, verification.token)
        
        if email_sent:
            messages.success(request, f'Verification email sent to {request.user.email}. Please check your inbox.')
        else:
            messages.error(request, 'Failed to send verification email. Please try again later.')
        
        return redirect('verify_email_sent')
        
    except Exception as e:
        logger.error(f"Error resending verification email: {e}")
        messages.error(request, 'An error occurred. Please try again.')
        return redirect('dashboard') 

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
    
    # Get active affiliate links and sponsored content
    from portfolio.models import AffiliateLink, SponsoredContent
    import random
    
    affiliate_links = AffiliateLink.objects.filter(is_active=True).order_by('display_order')[:6]
    
    # Get all active sponsored content and randomly select 2-3
    all_sponsored = SponsoredContent.objects.filter(is_active=True).order_by('display_order')
    sponsored_content = [c for c in all_sponsored if c.is_currently_active()]
    
    # Randomly select 2-3 sponsored items (or all if less than 3)
    if len(sponsored_content) > 3:
        sponsored_content = random.sample(sponsored_content, 3)
    elif len(sponsored_content) > 2:
        sponsored_content = random.sample(sponsored_content, 2)
    # If 2 or less, show all
    
    # Track views for sponsored content
    for content in sponsored_content:
        content.track_view()
    
    context = {
        'upcoming_dividends': upcoming_dividends,
        'affiliate_links': affiliate_links,
        'sponsored_content': sponsored_content,
    }
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
    
    # New advanced filters
    min_yield = request.GET.get('min_yield', '').strip()
    max_yield = request.GET.get('max_yield', '').strip()
    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()
    dividend_frequency = request.GET.get('frequency', '')
    tsx60_only = request.GET.get('tsx60', '') == 'on'
    etf_only = request.GET.get('etf', '') == 'on'
    has_dividend_filter = request.GET.get('has_dividend', '')
    
    # Save recent search to session
    if search_query:
        recent_searches = request.session.get('recent_searches', [])
        if search_query not in recent_searches:
            recent_searches.insert(0, search_query)
            recent_searches = recent_searches[:10]  # Keep only last 10
            request.session['recent_searches'] = recent_searches
            request.session.modified = True

    valid_sort_options = ['symbol', 'yield', 'sector', 'dividend_date', 'dividend_amount', 'price']
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
    
    # Advanced filters
    if min_yield:
        try:
            min_yield_val = float(min_yield)
            stocks = stocks.filter(latest_dividend_yield__gte=min_yield_val)
        except (ValueError, TypeError):
            min_yield = ''
    
    if max_yield:
        try:
            max_yield_val = float(max_yield)
            stocks = stocks.filter(latest_dividend_yield__lte=max_yield_val)
        except (ValueError, TypeError):
            max_yield = ''
    
    if min_price:
        try:
            min_price_val = float(min_price)
            stocks = stocks.filter(latest_price_value__gte=min_price_val)
        except (ValueError, TypeError):
            min_price = ''
    
    if max_price:
        try:
            max_price_val = float(max_price)
            stocks = stocks.filter(latest_price_value__lte=max_price_val)
        except (ValueError, TypeError):
            max_price = ''
    
    if dividend_frequency:
        stocks = stocks.filter(latest_dividend_frequency=dividend_frequency)
    
    if tsx60_only:
        stocks = stocks.filter(tsx60_member=True)
    
    if etf_only:
        stocks = stocks.filter(is_etf=True)
    
    if has_dividend_filter == 'yes':
        stocks = stocks.filter(has_dividend=True)
    elif has_dividend_filter == 'no':
        stocks = stocks.filter(has_dividend=False)

    # --- 7️⃣ Sorting map (simpler than if/elif chain)
    sort_map = {
        'symbol': ['symbol'],
        'yield': ['-latest_dividend_yield', 'symbol'],
        'sector': ['sector', 'symbol'],
        'dividend_amount': ['-latest_dividend_amount', 'symbol'],
        'price': ['-latest_price_value', 'symbol'],
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
    today = timezone.now().date()
    
    # Get user's watchlist if authenticated
    user_watchlist_ids = set()
    if request.user.is_authenticated:
        from portfolio.models import Watchlist
        user_watchlist_ids = set(
            Watchlist.objects.filter(user=request.user)
            .values_list('stock_id', flat=True)
        )
    
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
            'days_until': (stock.upcoming_dividend_date - today).days if stock.upcoming_dividend_date else None,
            'latest_price': (
                {
                    'price': stock.latest_price_value,
                    'date': stock.latest_price_date,
                } if stock.latest_price_value else None
            ),
            'has_dividend': stock.has_dividend,
            'in_watchlist': stock.id in user_watchlist_ids,
        }
        for stock in page_obj
    ]

    # Get unique dividend frequencies for filter dropdown
    frequencies = list(
        Dividend.objects.exclude(frequency='')
        .values_list('frequency', flat=True)
        .distinct()
        .order_by('frequency')
    )
    
    # --- 🔟 Stats (could be cached if large)
    context = {
        'stocks_with_dividends': stocks_with_data,
        'page_obj': page_obj,
        'search_query': search_query,
        'sector_filter': sector_filter,
        'sort_by': sort_by,
        'sectors': sectors,
        'frequencies': frequencies,
        'total_stocks_count': Stock.objects.count(),
        'dividend_stocks_count': Dividend.objects.values('stock').distinct().count(),
        'sectors_count': len(sectors),
        # Advanced filter values
        'min_yield': min_yield,
        'max_yield': max_yield,
        'min_price': min_price,
        'max_price': max_price,
        'dividend_frequency': dividend_frequency,
        'tsx60_only': tsx60_only,
        'etf_only': etf_only,
        'has_dividend_filter': has_dividend_filter,
    }

    # Add recent searches to context
    context['recent_searches'] = request.session.get('recent_searches', [])
    
    # Get sponsored content for sidebar - randomly select 1-2 featured stocks
    from portfolio.models import SponsoredContent
    import random
    
    all_featured = SponsoredContent.objects.filter(
        is_active=True, 
        content_type='featured_stock'
    ).order_by('display_order')
    featured_stocks = [c for c in all_featured if c.is_currently_active()]
    
    # Randomly select 1-2 featured stocks (or all if less than 2)
    if len(featured_stocks) > 2:
        featured_stocks = random.sample(featured_stocks, 2)
    # If 2 or less, show all
    
    context['sponsored_content'] = featured_stocks
    
    # Handle CSV export
    if request.GET.get('export') == '1':
        import csv
        from django.http import HttpResponse
        from datetime import datetime
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="stocks_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Symbol', 'Company Name', 'Sector', 'Price', 'Dividend Amount', 'Yield %', 'Frequency', 'Next Ex-Date', 'Days Until'])
        
        for item in stocks_with_data:
            writer.writerow([
                item['stock'].symbol,
                item['stock'].company_name,
                item['stock'].sector or '',
                item['latest_price']['price'] if item['latest_price'] else '',
                item['latest_dividend']['amount'] if item['latest_dividend'] else '',
                item['latest_dividend']['yield_percent'] if item['latest_dividend'] and item['latest_dividend']['yield_percent'] else '',
                item['latest_dividend']['frequency'] if item['latest_dividend'] else '',
                item['upcoming_dividend_date'].strftime('%Y-%m-%d') if item['upcoming_dividend_date'] else '',
                item['days_until'] if item['days_until'] is not None else '',
            ])
        
        return response
    
    return render(request, 'all_stocks.html', context)


def track_affiliate_click(request, affiliate_id):
    """Track affiliate link clicks and redirect"""
    from portfolio.models import AffiliateLink
    
    try:
        affiliate = AffiliateLink.objects.get(id=affiliate_id, is_active=True)
        affiliate.track_click()
        logger.info(f"Affiliate click tracked: {affiliate.name} (ID: {affiliate_id})")
        return redirect(affiliate.affiliate_url)
    except AffiliateLink.DoesNotExist:
        messages.error(request, 'Invalid affiliate link.')
        return redirect('home')
    except Exception as e:
        logger.error(f"Error tracking affiliate click: {e}")
        return redirect('home')


def track_sponsored_click(request, content_id):
    """Track sponsored content clicks and redirect"""
    from portfolio.models import SponsoredContent
    
    try:
        content = SponsoredContent.objects.get(id=content_id)
        if not content.is_currently_active():
            messages.error(request, 'This content is no longer available.')
            return redirect('home')
        
        content.track_click()
        logger.info(f"Sponsored content click tracked: {content.title} (ID: {content_id})")
        
        if content.link_url:
            return redirect(content.link_url)
        elif content.stock:
            return redirect('stock_detail', symbol=content.stock.symbol)
        else:
            return redirect('home')
    except SponsoredContent.DoesNotExist:
        messages.error(request, 'Invalid content link.')
        return redirect('home')
    except Exception as e:
        logger.error(f"Error tracking sponsored click: {e}")
        return redirect('home')


@csrf_exempt
def health_check(request):
    """
    Health check API endpoint for monitoring
    Returns system health status including database connectivity and key services
    """
    from django.db import connection
    from django.core.cache import cache
    
    health_status = {
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'version': '1.0.0',
        'checks': {}
    }
    
    overall_healthy = True
    http_status = 200
    
    # Check Database Connectivity
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health_status['checks']['database'] = {
            'status': 'healthy',
            'message': 'Database connection successful'
        }
    except Exception as e:
        health_status['checks']['database'] = {
            'status': 'unhealthy',
            'message': f'Database connection failed: {str(e)}'
        }
        overall_healthy = False
        http_status = 503
    
    # Check Key Models/Tables
    try:
        stock_count = Stock.objects.count()
        health_status['checks']['stocks_table'] = {
            'status': 'healthy',
            'message': f'Stocks table accessible',
            'count': stock_count
        }
    except Exception as e:
        health_status['checks']['stocks_table'] = {
            'status': 'unhealthy',
            'message': f'Stocks table error: {str(e)}'
        }
        overall_healthy = False
        http_status = 503
    
    # Check StockPrice table
    try:
        price_count = StockPrice.objects.count()
        latest_price = StockPrice.objects.order_by('-price_date').first()
        health_status['checks']['stock_prices_table'] = {
            'status': 'healthy',
            'message': 'Stock prices table accessible',
            'count': price_count,
            'latest_price_date': latest_price.price_date.isoformat() if latest_price else None
        }
    except Exception as e:
        health_status['checks']['stock_prices_table'] = {
            'status': 'unhealthy',
            'message': f'Stock prices table error: {str(e)}'
        }
        overall_healthy = False
        http_status = 503
    
    # Check Dividends table
    try:
        dividend_count = Dividend.objects.count()
        health_status['checks']['dividends_table'] = {
            'status': 'healthy',
            'message': 'Dividends table accessible',
            'count': dividend_count
        }
    except Exception as e:
        health_status['checks']['dividends_table'] = {
            'status': 'unhealthy',
            'message': f'Dividends table error: {str(e)}'
        }
        overall_healthy = False
        http_status = 503
    
    # Check Cache (if available)
    try:
        test_key = 'health_check_test'
        cache.set(test_key, 'test_value', 10)
        cached_value = cache.get(test_key)
        cache.delete(test_key)
        health_status['checks']['cache'] = {
            'status': 'healthy' if cached_value == 'test_value' else 'degraded',
            'message': 'Cache is operational' if cached_value == 'test_value' else 'Cache may not be working properly'
        }
    except Exception as e:
        health_status['checks']['cache'] = {
            'status': 'degraded',
            'message': f'Cache check failed: {str(e)}'
        }
        # Cache failure doesn't make the system unhealthy, just degraded
    
    # Check User Authentication System
    try:
        from django.contrib.auth.models import User
        user_count = User.objects.count()
        health_status['checks']['authentication'] = {
            'status': 'healthy',
            'message': 'Authentication system accessible',
            'user_count': user_count
        }
    except Exception as e:
        health_status['checks']['authentication'] = {
            'status': 'unhealthy',
            'message': f'Authentication system error: {str(e)}'
        }
        overall_healthy = False
        http_status = 503
    
    # Check Recent Data Activity (last 24 hours)
    try:
        from datetime import timedelta
        yesterday = timezone.now() - timedelta(days=1)
        recent_prices = StockPrice.objects.filter(price_date__gte=yesterday.date()).count()
        health_status['checks']['recent_activity'] = {
            'status': 'healthy' if recent_prices > 0 else 'warning',
            'message': f'Recent price updates: {recent_prices} in last 24 hours',
            'count': recent_prices
        }
    except Exception as e:
        health_status['checks']['recent_activity'] = {
            'status': 'degraded',
            'message': f'Could not check recent activity: {str(e)}'
        }
    
    # Set overall status
    if not overall_healthy:
        health_status['status'] = 'unhealthy'
    elif any(check.get('status') == 'degraded' for check in health_status['checks'].values()):
        health_status['status'] = 'degraded'
    
    # Add summary
    health_status['summary'] = {
        'total_checks': len(health_status['checks']),
        'healthy_checks': sum(1 for check in health_status['checks'].values() if check.get('status') == 'healthy'),
        'unhealthy_checks': sum(1 for check in health_status['checks'].values() if check.get('status') == 'unhealthy'),
        'degraded_checks': sum(1 for check in health_status['checks'].values() if check.get('status') == 'degraded')
    }
    
    return JsonResponse(health_status, status=http_status)


def stock_search_autocomplete(request):
    """API endpoint for stock search autocomplete"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'results': []})
    
    # Search stocks by symbol, code, or company name
    stocks = Stock.objects.filter(
        Q(symbol__icontains=query)
        | Q(company_name__icontains=query)
        | Q(code__icontains=query)
    ).order_by('symbol')[:10]  # Limit to 10 results
    
    results = []
    for stock in stocks:
        results.append({
            'symbol': stock.symbol,
            'code': stock.code,
            'company_name': stock.company_name,
            'sector': stock.sector or '',
            'url': f'/stocks/{stock.symbol}/'
        })
    
    return JsonResponse({'results': results})


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
    
    # If no price found, try to fetch from API
    if not latest_price:
        from portfolio.utils.price_fetcher import get_or_fetch_stock_price
        latest_price = get_or_fetch_stock_price(stock)
    
    # Get dividend, default to 0 if not present
    dividend = stock.latest_dividends[0] if stock.latest_dividends else None
    if not dividend:
        # Create a default dividend object with 0 values
        dividend = type('obj', (object,), {
            'amount': 0,
            'yield_percent': 0,
            'frequency': 'Unknown',
            'ex_dividend_date': None,
            'currency': 'CAD'
        })()
    
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
        
        # Get user's notes for this stock
        try:
            user_notes = StockNote.objects.filter(
                user=request.user, stock=stock
            ).order_by('-created_at')[:5]  # Show last 5 notes
        except (ProgrammingError, OperationalError, DatabaseError, Exception) as e:
            # Table might not exist yet if migration hasn't been run
            user_notes = []
            logger.warning(f"StockNote table not found: {e}")
    else:
        user_notes = []
    
    # Calculate dividend growth and consistency metrics
    today = timezone.now().date()
    all_dividends = Dividend.objects.filter(stock=stock, ex_dividend_date__isnull=False).order_by('ex_dividend_date')
    
    dividend_growth_rate = None
    dividend_consistency_score = 0
    annual_dividend_income = 0
    
    if all_dividends.exists() and dividend and dividend.amount:
        # Calculate dividend growth rate (last 2 years)
        two_years_ago = today - timedelta(days=730)
        recent_dividends = all_dividends.filter(ex_dividend_date__gte=two_years_ago)
        
        if recent_dividends.count() >= 4:  # Need at least 4 dividends to calculate growth
            first_year_dividends = recent_dividends[:recent_dividends.count()//2]
            second_year_dividends = recent_dividends[recent_dividends.count()//2:]
            
            if first_year_dividends.exists() and second_year_dividends.exists():
                first_year_avg = sum(float(d.amount) for d in first_year_dividends) / first_year_dividends.count()
                second_year_avg = sum(float(d.amount) for d in second_year_dividends) / second_year_dividends.count()
                
                if first_year_avg > 0:
                    dividend_growth_rate = ((second_year_avg - first_year_avg) / first_year_avg) * 100
        
        # Calculate consistency score (how regular are the payments)
        if recent_dividends.count() >= 2:
            dates = [d.ex_dividend_date for d in recent_dividends if d.ex_dividend_date]
            if len(dates) >= 2:
                # Check if dividends are roughly evenly spaced
                intervals = []
                for i in range(1, len(dates)):
                    days_between = (dates[i] - dates[i-1]).days
                    intervals.append(days_between)
                
                if intervals:
                    avg_interval = sum(intervals) / len(intervals)
                    # Score based on how consistent intervals are (lower variance = higher score)
                    variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
                    # Normalize to 0-100 score
                    dividend_consistency_score = max(0, min(100, 100 - (variance / 10)))
        
        # Calculate annual dividend income (based on current dividend)
        if dividend.frequency:
            if 'Monthly' in dividend.frequency:
                annual_dividend_income = float(dividend.amount) * 12
            elif 'Quarterly' in dividend.frequency:
                annual_dividend_income = float(dividend.amount) * 4
            elif 'Semi-Annual' in dividend.frequency:
                annual_dividend_income = float(dividend.amount) * 2
            elif 'Annual' in dividend.frequency:
                annual_dividend_income = float(dividend.amount)
            else:
                # Estimate based on recent frequency
                recent_count = recent_dividends.count()
                if recent_count > 0:
                    days_span = (recent_dividends.last().ex_dividend_date - recent_dividends.first().ex_dividend_date).days
                    if days_span > 0:
                        payments_per_year = (recent_count * 365) / days_span
                        annual_dividend_income = float(dividend.amount) * payments_per_year
    
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
        'user_notes': user_notes,
        'dividend_growth_rate': dividend_growth_rate,
        'dividend_consistency_score': dividend_consistency_score,
        'annual_dividend_income': annual_dividend_income,
        'today': today,
    }
    
    return render(request, 'stock_detail.html', context)


def stock_comparison(request):
    """Compare 2-3 stocks side-by-side"""
    from django.db.models import Prefetch
    
    # Get stock symbols from query parameters (symbol1, symbol2, symbol3)
    symbol1 = request.GET.get('symbol1', '').upper().strip()
    symbol2 = request.GET.get('symbol2', '').upper().strip()
    symbol3 = request.GET.get('symbol3', '').upper().strip()
    
    # Collect valid symbols
    symbols = [s for s in [symbol1, symbol2, symbol3] if s]
    
    # Validate: need at least 2 symbols, max 3
    if len(symbols) < 2:
        messages.warning(request, 'Please select at least 2 stocks to compare.')
        return render(request, 'stock_comparison.html', {
            'stocks_data': [],
            'symbols': symbols,
        })
    
    if len(symbols) > 3:
        messages.warning(request, 'You can compare up to 3 stocks at a time.')
        symbols = symbols[:3]
    
    # Fetch all stocks with related data in optimized queries
    stocks = Stock.objects.filter(symbol__in=symbols).prefetch_related(
        Prefetch('prices', queryset=StockPrice.objects.order_by('-price_date'), to_attr='latest_prices'),
        Prefetch('dividends', queryset=Dividend.objects.order_by('-ex_dividend_date'), to_attr='latest_dividends'),
        Prefetch('valuations', queryset=ValuationMetric.objects.order_by('-metric_date'), to_attr='latest_valuations'),
        Prefetch('analyst_ratings', queryset=AnalystRating.objects.order_by('-rating_date'), to_attr='latest_ratings'),
    )
    
    # Create a dictionary for quick lookup
    stocks_dict = {stock.symbol: stock for stock in stocks}
    
    # Build comparison data
    stocks_data = []
    for symbol in symbols:
        if symbol not in stocks_dict:
            messages.error(request, f'Stock {symbol} not found.')
            continue
        
        stock = stocks_dict[symbol]
        latest_price = stock.latest_prices[0] if stock.latest_prices else None
        dividend = stock.latest_dividends[0] if stock.latest_dividends else None
        valuation = stock.latest_valuations[0] if stock.latest_valuations else None
        analyst_rating = stock.latest_ratings[0] if stock.latest_ratings else None
        
        # Calculate price change if we have 52-week data
        price_change_52w = None
        if latest_price and latest_price.fiftytwo_week_high and latest_price.fiftytwo_week_low:
            if latest_price.last_price:
                range_size = float(latest_price.fiftytwo_week_high) - float(latest_price.fiftytwo_week_low)
                if range_size > 0:
                    price_change_52w = ((float(latest_price.last_price) - float(latest_price.fiftytwo_week_low)) / range_size) * 100
        
        stocks_data.append({
            'stock': stock,
            'latest_price': latest_price,
            'dividend': dividend,
            'valuation': valuation,
            'analyst_rating': analyst_rating,
            'price_change_52w': price_change_52w,
        })
    
    context = {
        'stocks_data': stocks_data,
        'symbols': symbols,
    }
    
    return render(request, 'stock_comparison.html', context)


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
    
    # Advanced filters
    sector_filter = request.GET.get('sector', '')
    min_yield = request.GET.get('min_yield', '').strip()
    max_yield = request.GET.get('max_yield', '').strip()
    min_amount = request.GET.get('min_amount', '').strip()
    max_amount = request.GET.get('max_amount', '').strip()
    search_query = request.GET.get('search', '').strip()
    
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
    
    # Apply advanced filters
    if sector_filter:
        dividend_query = dividend_query.filter(stock__sector=sector_filter)
    
    if search_query:
        dividend_query = dividend_query.filter(
            Q(stock__symbol__icontains=search_query)
            | Q(stock__company_name__icontains=search_query)
        )
    
    if min_yield:
        try:
            min_yield_val = float(min_yield)
            dividend_query = dividend_query.filter(yield_percent__gte=min_yield_val)
        except (ValueError, TypeError):
            min_yield = ''
    
    if max_yield:
        try:
            max_yield_val = float(max_yield)
            dividend_query = dividend_query.filter(yield_percent__lte=max_yield_val)
        except (ValueError, TypeError):
            max_yield = ''
    
    if min_amount:
        try:
            min_amount_val = float(min_amount)
            dividend_query = dividend_query.filter(amount__gte=min_amount_val)
        except (ValueError, TypeError):
            min_amount = ''
    
    if max_amount:
        try:
            max_amount_val = float(max_amount)
            dividend_query = dividend_query.filter(amount__lte=max_amount_val)
        except (ValueError, TypeError):
            max_amount = ''
    
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
    
    # Calculate portfolio income if portfolio filter is active
    portfolio_income = None
    if filter_type == 'portfolio' and request.user.is_authenticated:
        portfolio_income = 0
        portfolio_items = UserPortfolio.objects.filter(user=request.user).select_related('stock')
        portfolio_dict = {item.stock_id: item.shares_owned for item in portfolio_items}
        
        for dividend in dividend_query:
            if dividend.stock_id in portfolio_dict:
                shares = portfolio_dict[dividend.stock_id]
                portfolio_income += float(dividend.amount or 0) * shares
    
    # Get unique sectors for filter dropdown
    sectors = list(
        Stock.objects.exclude(sector='')
        .values_list('sector', flat=True)
        .distinct()
        .order_by('sector')
    )
    
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
    
    # Handle CSV export
    if request.GET.get('export') == '1':
        import csv
        from django.http import HttpResponse
        from datetime import datetime
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="dividend_calendar_{year}_{month:02d}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Date', 'Symbol', 'Company Name', 'Dividend Amount', 'Yield %', 'Frequency', 'Sector'])
        
        for day_data in calendar_days:
            if day_data['is_current_month'] and day_data['dividends']:
                for dividend in day_data['dividends']:
                    writer.writerow([
                        day_data['date'].strftime('%Y-%m-%d'),
                        dividend.stock.symbol,
                        dividend.stock.company_name,
                        dividend.amount or '',
                        dividend.yield_percent or '',
                        dividend.frequency or '',
                        dividend.stock.sector or '',
                    ])
        
        return response
    
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
        'sectors': sectors,
        'sector_filter': sector_filter,
        'search_query': search_query,
        'min_yield': min_yield,
        'max_yield': max_yield,
        'min_amount': min_amount,
        'max_amount': max_amount,
        'portfolio_income': portfolio_income,
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
        
        # Prepare data efficiently with price changes
        watchlist_data = []
        dividend_stocks_count = 0
        sectors = set()
        today = timezone.now().date()
        seven_days_ago = today - timedelta(days=7)
        thirty_days_ago = today - timedelta(days=30)
        
        # Get upcoming dividends for watchlist stocks
        upcoming_dividends = Dividend.objects.filter(
            stock__in=[item.stock for item in watchlist_items],
            ex_dividend_date__gte=today,
            ex_dividend_date__lte=today + timedelta(days=30)
        ).select_related('stock').order_by('ex_dividend_date')[:5]
        
        # Get recent news for watchlist stocks
        from portfolio.models import StockNews
        recent_news = StockNews.objects.filter(
            stock__in=[item.stock for item in watchlist_items]
        ).select_related('stock').order_by('-published_at')[:5]
        
        for item in watchlist_items:
            in_portfolio = item.stock_id in portfolio_stock_ids
            
            latest_price = None
            price_change_7d = None
            price_change_30d = None
            if item.latest_price_value:
                latest_price = type('obj', (object,), {
                    'last_price': item.latest_price_value,
                    'price_date': item.latest_price_date
                })()
                
                # Calculate price changes
                price_7d_ago = StockPrice.objects.filter(
                    stock=item.stock,
                    price_date__lte=seven_days_ago
                ).order_by('-price_date').first()
                
                price_30d_ago = StockPrice.objects.filter(
                    stock=item.stock,
                    price_date__lte=thirty_days_ago
                ).order_by('-price_date').first()
                
                if price_7d_ago and price_7d_ago.last_price:
                    price_change_7d = ((float(item.latest_price_value) - float(price_7d_ago.last_price)) / float(price_7d_ago.last_price)) * 100
                
                if price_30d_ago and price_30d_ago.last_price:
                    price_change_30d = ((float(item.latest_price_value) - float(price_30d_ago.last_price)) / float(price_30d_ago.last_price)) * 100
            
            latest_dividend = None
            days_until_dividend = None
            if item.latest_dividend_amount:
                latest_dividend = type('obj', (object,), {
                    'amount': item.latest_dividend_amount,
                    'yield_percent': item.latest_dividend_yield,
                    'ex_dividend_date': item.latest_dividend_date,
                    'frequency': item.latest_dividend_frequency
                })()
                dividend_stocks_count += 1
                
                if item.latest_dividend_date:
                    days_until_dividend = (item.latest_dividend_date - today).days
            
            if item.stock.sector:
                sectors.add(item.stock.sector)
            
            watchlist_data.append({
                'stock': item.stock,
                'latest_price': latest_price,
                'latest_dividend': latest_dividend,
                'in_portfolio': in_portfolio,
                'watchlist_item': item,
                'price_change_7d': price_change_7d,
                'price_change_30d': price_change_30d,
                'days_until_dividend': days_until_dividend,
            })
        
        # Count stocks in portfolio
        in_portfolio_count = sum(1 for item in watchlist_data if item['in_portfolio'])
        
        # Calculate insights
        total_value = sum(float(item['latest_price'].last_price) for item in watchlist_data if item['latest_price'])
        avg_yield = sum(float(item['latest_dividend'].yield_percent) for item in watchlist_data if item['latest_dividend']) / dividend_stocks_count if dividend_stocks_count > 0 else 0
        
        return render(request, 'watchlist.html', {
            'watchlist_items': watchlist_data,
            'dividend_stocks_count': dividend_stocks_count,
            'sectors_count': len(sectors),
            'watchlist_count': len(watchlist_items),
            'in_portfolio_count': in_portfolio_count,
            'upcoming_dividends': upcoming_dividends,
            'recent_news': recent_news,
            'total_value': total_value,
            'avg_yield': avg_yield,
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
            # Check if price is missing and try to fetch it
            price_value = item.latest_price_value
            price_date = item.latest_price_date
            
            if not price_value:
                # Try to fetch price from API
                from portfolio.utils.price_fetcher import get_or_fetch_stock_price
                fetched_price = get_or_fetch_stock_price(item.stock)
                if fetched_price:
                    price_value = fetched_price.last_price
                    price_date = fetched_price.price_date
                    # Update the item's annotations for consistency
                    item.latest_price_value = price_value
                    item.latest_price_date = price_date
            
            # Calculate current value and gains
            current_value = 0
            if price_value and item.shares_owned:
                current_value = float(item.shares_owned * price_value)
            
            investment_value = 0
            if item.average_cost and item.shares_owned:
                investment_value = float(item.shares_owned * item.average_cost)
            
            gain_loss = current_value - investment_value
            
            # Ensure dividend defaults to 0 if not present
            dividend_amount = item.latest_dividend_amount if item.latest_dividend_amount else 0
            dividend_yield = item.latest_dividend_yield if item.latest_dividend_yield else 0
            dividend_frequency = item.latest_dividend_frequency if item.latest_dividend_frequency else 'Unknown'
            dividend_date = item.latest_dividend_date if item.latest_dividend_date else None
            
            # Calculate dividend income using service (will handle 0 values)
            dividend_income = PortfolioService.calculate_annual_dividend(
                dividend_amount,
                item.shares_owned,
                dividend_frequency
            )
            
            # Create mock objects for template compatibility
            latest_price = None
            if price_value:
                latest_price = type('obj', (object,), {
                    'last_price': price_value,
                    'price_date': price_date
                })()
            
            # Always create dividend object, defaulting to 0 if not present
            latest_dividend = type('obj', (object,), {
                'amount': dividend_amount,
                'yield_percent': dividend_yield,
                'frequency': dividend_frequency,
                'ex_dividend_date': dividend_date
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
            
            # Calculate expected dividend for upcoming payment (default to 0 if no dividend)
            expected_dividend = 0
            if dividend_amount and item.shares_owned:
                expected_dividend = float(dividend_amount * item.shares_owned)
            
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
        
        # Get realized gains from transactions
        try:
            from django.db import DatabaseError, ProgrammingError, OperationalError
            realized_gains_data = TransactionService.get_realized_gains(request.user)
            total_realized_gain = realized_gains_data['total_realized_gain']
            
            # Add unrealized gains to each portfolio item
            for data in portfolio_data:
                unrealized = TransactionService.get_unrealized_gains(request.user, data['item'].stock)
                if unrealized:
                    data['unrealized_gain'] = unrealized['unrealized_gain']
                    data['unrealized_gain_percent'] = unrealized['unrealized_gain_percent']
                else:
                    data['unrealized_gain'] = data['gain_loss']  # Fallback to calculated gain_loss
                    data['unrealized_gain_percent'] = data['roi_percent']
        except (ProgrammingError, OperationalError, DatabaseError):
            # Transaction table might not exist yet
            total_realized_gain = 0
            for data in portfolio_data:
                data['unrealized_gain'] = data['gain_loss']
                data['unrealized_gain_percent'] = data['roi_percent']
        except Exception as e:
            logger.warning(f"Error getting transaction gains: {e}")
            total_realized_gain = 0
            for data in portfolio_data:
                data['unrealized_gain'] = data['gain_loss']
                data['unrealized_gain_percent'] = data['roi_percent']
        
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
            'total_realized_gain': total_realized_gain,
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
def transactions_list(request, symbol=None):
    """List all transactions for the user, optionally filtered by stock"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        
        # Test if Transaction model is accessible
        try:
            test_query = Transaction.objects.all()
        except (ProgrammingError, OperationalError, DatabaseError) as db_error:
            logger.error(f"Database error accessing Transaction: {db_error}")
            messages.error(request, f'Transaction table does not exist. Please run: python manage.py migrate. Error: {str(db_error)}')
            return redirect('portfolio')
        except Exception as model_error:
            logger.error(f"Model error: {model_error}")
            messages.error(request, f'Error accessing Transaction model: {str(model_error)}')
            return redirect('portfolio')
        
        transactions = Transaction.objects.filter(user=request.user).select_related('stock').order_by('-transaction_date', '-created_at')
        
        stock = None
        if symbol:
            try:
                stock = Stock.objects.get(symbol=symbol.upper())
                transactions = transactions.filter(stock=stock)
            except Stock.DoesNotExist:
                messages.warning(request, f'Stock "{symbol}" not found. Showing all transactions.')
                symbol = None  # Reset symbol so we show all transactions
        
        # Pagination
        paginator = Paginator(transactions, 25)
        page = request.GET.get('page', 1)
        try:
            transactions_page = paginator.page(page)
        except PageNotAnInteger:
            transactions_page = paginator.page(1)
        except EmptyPage:
            transactions_page = paginator.page(paginator.num_pages)
        
        # Calculate summary statistics
        try:
            total_realized = TransactionService.get_realized_gains(request.user)
            total_realized_gain = total_realized.get('total_realized_gain', 0)
        except Exception as e:
            logger.warning(f"Error calculating realized gains: {e}")
            total_realized_gain = 0
        
        total_buys = transactions.filter(transaction_type='BUY').count()
        total_sells = transactions.filter(transaction_type='SELL').count()
        
        context = {
            'transactions': transactions_page,
            'symbol': symbol,
            'stock': stock,
            'total_realized_gain': total_realized_gain,
            'total_buys': total_buys,
            'total_sells': total_sells,
        }
        
        return render(request, 'transactions/list.html', context)
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.error(f"Transaction table not found: {e}", exc_info=True)
        messages.error(request, f'Transaction feature is not available. Please run: python manage.py migrate. Error: {str(e)}')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error in transactions_list: {e}", exc_info=True)
        messages.error(request, f'An error occurred while loading transactions: {str(e)}')
        return redirect('portfolio')


@login_required
def create_transaction(request, symbol=None):
    """Create a new transaction"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        
        # Test if Transaction model is accessible
        try:
            Transaction.objects.model
        except (ProgrammingError, OperationalError, DatabaseError) as db_error:
            logger.error(f"Database error accessing Transaction: {db_error}")
            messages.error(request, f'Transaction table does not exist. Please run: python manage.py migrate. Error: {str(db_error)}')
            return redirect('portfolio')
        except Exception as model_error:
            logger.error(f"Model error: {model_error}")
            messages.error(request, f'Error accessing Transaction model: {str(model_error)}')
            return redirect('portfolio')
        
        stock = None
        if symbol:
            try:
                stock = Stock.objects.get(symbol=symbol.upper())
            except Stock.DoesNotExist:
                messages.error(request, f'Stock "{symbol}" not found. Please select a stock from the dropdown.')
                symbol = None  # Reset to allow user to select from dropdown
        
        if request.method == 'POST':
            try:
                stock_symbol = request.POST.get('stock_symbol', symbol or '').upper()
                if not stock_symbol:
                    messages.error(request, 'Stock symbol is required.')
                    return redirect('transactions_list')
                
                stock = get_object_or_404(Stock, symbol=stock_symbol)
                transaction_type = request.POST.get('transaction_type')
                transaction_date = request.POST.get('transaction_date')
                shares = float(request.POST.get('shares', 0))
                price_per_share = float(request.POST.get('price_per_share', 0))
                fees = float(request.POST.get('fees', 0))
                notes = request.POST.get('notes', '')
                cost_basis_method = request.POST.get('cost_basis_method', 'FIFO')
                
                if transaction_type not in ['BUY', 'SELL', 'DIVIDEND', 'SPLIT', 'MERGER']:
                    messages.error(request, 'Invalid transaction type.')
                    if symbol:
                        return redirect('create_transaction_by_symbol', symbol=stock_symbol)
                    return redirect('create_transaction')
                
                if shares <= 0 or price_per_share <= 0:
                    messages.error(request, 'Shares and price must be positive numbers.')
                    if symbol:
                        return redirect('create_transaction_by_symbol', symbol=stock_symbol)
                    return redirect('create_transaction')
                
                # Create transaction
                transaction = Transaction.objects.create(
                    user=request.user,
                    stock=stock,
                    transaction_type=transaction_type,
                    transaction_date=transaction_date,
                    shares=shares,
                    price_per_share=price_per_share,
                    fees=fees,
                    notes=notes,
                    cost_basis_method=cost_basis_method
                )
                
                # For sell transactions, calculate realized gain/loss
                if transaction_type == 'SELL':
                    try:
                        cost_basis, transactions_used, error = TransactionService.calculate_cost_basis(
                            request.user, stock, shares, cost_basis_method
                        )
                        if error:
                            messages.warning(request, f'Transaction created but cost basis calculation failed: {error}. Gain/loss will be calculated when you have buy transactions.')
                            # Set to None so it shows as "-" in the list
                            transaction.realized_gain_loss = None
                        else:
                            # Ensure cost_basis is not None
                            if cost_basis is not None:
                                transaction.calculate_realized_gain_loss(cost_basis)
                            else:
                                transaction.realized_gain_loss = None
                        transaction.save()
                    except Exception as e:
                        logger.error(f"Error calculating gain/loss for sell transaction: {e}", exc_info=True)
                        messages.warning(request, f'Transaction created but gain/loss calculation failed: {str(e)}')
                        transaction.realized_gain_loss = None
                        transaction.save()
                
                # Update portfolio from transactions
                TransactionService.update_portfolio_from_transactions(request.user, stock)
                
                messages.success(request, f'Transaction added successfully!')
                # Redirect to transactions list, optionally filtered by symbol
                if symbol:
                    return redirect('transactions_list_by_symbol', symbol=stock_symbol)
                return redirect('transactions_list')
                
            except ValueError as e:
                messages.error(request, f'Invalid input: {str(e)}')
                logger.error(f"ValueError in create_transaction: {e}")
            except Stock.DoesNotExist:
                messages.error(request, f'Stock "{stock_symbol}" not found. Please select a valid stock.')
                logger.error(f"Stock not found: {stock_symbol}")
            except Exception as e:
                logger.error(f"Error creating transaction: {e}", exc_info=True)
                messages.error(request, f'An error occurred while creating the transaction: {str(e)}')
        
        # Get all stocks for dropdown
        stocks = Stock.objects.all().order_by('symbol')
        
        context = {
            'stock': stock,
            'stocks': stocks,
            'transaction_types': Transaction.TRANSACTION_TYPES,
            'cost_basis_methods': Transaction.COST_BASIS_METHODS,
        }
        
        return render(request, 'transactions/create.html', context)
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.warning(f"Transaction table not found: {e}")
        messages.error(request, 'Transaction feature is not available yet. Please run migrations.')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error in create_transaction: {e}")
        messages.error(request, 'An error occurred.')
        return redirect('transactions_list')


@login_required
def edit_transaction(request, transaction_id):
    """Edit an existing transaction"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        
        # Test if Transaction model is accessible
        try:
            Transaction.objects.model
        except (ProgrammingError, OperationalError, DatabaseError) as db_error:
            logger.error(f"Database error accessing Transaction: {db_error}")
            messages.error(request, f'Transaction table does not exist. Please run: python manage.py migrate. Error: {str(db_error)}')
            return redirect('portfolio')
        except Exception as model_error:
            logger.error(f"Model error: {model_error}")
            messages.error(request, f'Error accessing Transaction model: {str(model_error)}')
            return redirect('portfolio')
        
        transaction = get_object_or_404(Transaction, id=transaction_id, user=request.user)
        stock = transaction.stock
        
        if request.method == 'POST':
            try:
                transaction_type = request.POST.get('transaction_type')
                transaction_date = request.POST.get('transaction_date')
                shares = float(request.POST.get('shares', 0))
                price_per_share = float(request.POST.get('price_per_share', 0))
                fees = float(request.POST.get('fees', 0))
                notes = request.POST.get('notes', '')
                cost_basis_method = request.POST.get('cost_basis_method', 'FIFO')
                
                if transaction_type not in ['BUY', 'SELL', 'DIVIDEND', 'SPLIT', 'MERGER']:
                    messages.error(request, 'Invalid transaction type.')
                    # Stay on edit page to show error
                elif shares <= 0 or price_per_share <= 0:
                    messages.error(request, 'Shares and price must be positive numbers.')
                    # Stay on edit page to show error
                else:
                    # Update transaction
                    transaction.transaction_type = transaction_type
                    transaction.transaction_date = transaction_date
                    transaction.shares = shares
                    transaction.price_per_share = price_per_share
                    transaction.fees = fees
                    transaction.notes = notes
                    transaction.cost_basis_method = cost_basis_method
                    transaction.is_processed = False  # Reset processed flag
                    transaction.save()
                    
                    # Recalculate realized gain/loss for sell transactions
                    if transaction_type == 'SELL':
                        try:
                            cost_basis, transactions_used, error = TransactionService.calculate_cost_basis(
                                request.user, stock, shares, cost_basis_method
                            )
                            if error:
                                messages.warning(request, f'Transaction updated but cost basis calculation failed: {error}')
                                transaction.realized_gain_loss = None
                            else:
                                if cost_basis is not None:
                                    transaction.calculate_realized_gain_loss(cost_basis)
                                else:
                                    transaction.realized_gain_loss = None
                            transaction.save()
                        except Exception as e:
                            logger.error(f"Error calculating gain/loss for sell transaction: {e}", exc_info=True)
                            messages.warning(request, f'Transaction updated but gain/loss calculation failed: {str(e)}')
                            transaction.realized_gain_loss = None
                            transaction.save()
                    
                    # Update portfolio from transactions
                    TransactionService.update_portfolio_from_transactions(request.user, stock)
                    
                    messages.success(request, 'Transaction updated successfully!')
                    # Redirect to transactions list, optionally filtered by symbol
                    return redirect('transactions_list_by_symbol', symbol=stock.symbol)
                
            except ValueError as e:
                messages.error(request, f'Invalid input: {str(e)}')
                logger.error(f"ValueError in edit_transaction: {e}")
                # Stay on edit page to show error
            except Exception as e:
                logger.error(f"Error updating transaction: {e}", exc_info=True)
                messages.error(request, f'An error occurred while updating the transaction: {str(e)}')
                # Stay on edit page to show error
        
        context = {
            'transaction': transaction,
            'transaction_types': Transaction.TRANSACTION_TYPES,
            'cost_basis_methods': Transaction.COST_BASIS_METHODS,
        }
        
        return render(request, 'transactions/edit.html', context)
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.error(f"Transaction table not found: {e}", exc_info=True)
        messages.error(request, f'Transaction feature is not available. Please run: python manage.py migrate. Error: {str(e)}')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error in edit_transaction: {e}", exc_info=True)
        messages.error(request, f'An error occurred: {str(e)}')
        return redirect('transactions_list')


@login_required
@require_POST
def delete_transaction(request, transaction_id):
    """Delete a transaction"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        
        transaction = get_object_or_404(Transaction, id=transaction_id, user=request.user)
        stock = transaction.stock
        symbol = stock.symbol
        
        transaction.delete()
        
        # Update portfolio from transactions - recalculate from ALL remaining transactions
        TransactionService.update_portfolio_from_transactions(request.user, stock, recalculate_all=True)
        
        messages.success(request, 'Transaction deleted successfully!')
        # Redirect to transactions list, optionally filtered by symbol
        if symbol:
            return redirect('transactions_list_by_symbol', symbol=symbol)
        else:
            return redirect('transactions_list')
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.warning(f"Transaction table not found: {e}")
        messages.error(request, 'Transaction feature is not available yet. Please run migrations.')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error deleting transaction: {e}")
        messages.error(request, 'An error occurred while deleting the transaction.')
        return redirect('transactions_list')


@login_required
@require_POST
def delete_all_transactions(request):
    """Delete all transactions for the current user"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        
        # Get count before deletion
        transaction_count = Transaction.objects.filter(user=request.user).count()
        
        if transaction_count == 0:
            messages.info(request, 'You have no transactions to delete.')
            return redirect('transactions_list')
        
        # Get all unique stocks before deletion
        affected_stocks = set(
            Transaction.objects.filter(user=request.user)
            .values_list('stock', flat=True)
            .distinct()
        )
        
        # Delete all transactions
        Transaction.objects.filter(user=request.user).delete()
        
        # Recalculate portfolio for all affected stocks (will remove them if no shares left)
        for stock_id in affected_stocks:
            try:
                from portfolio.models import Stock
                stock = Stock.objects.get(id=stock_id)
                TransactionService.update_portfolio_from_transactions(request.user, stock, recalculate_all=True)
            except Stock.DoesNotExist:
                continue
        
        messages.success(request, f'Successfully deleted all {transaction_count} transaction(s) and cleared your portfolio.')
        return redirect('transactions_list')
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.warning(f"Transaction table not found: {e}")
        messages.error(request, 'Transaction feature is not available yet. Please run migrations.')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error deleting all transactions: {e}", exc_info=True)
        messages.error(request, 'An error occurred while deleting transactions.')
        return redirect('transactions_list')


@login_required
@require_POST
def delete_portfolio_stock(request, symbol):
    """Remove a stock from user's portfolio"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        
        stock = get_object_or_404(Stock, symbol=symbol.upper())
        portfolio_item = UserPortfolio.objects.filter(user=request.user, stock=stock).first()
        
        if not portfolio_item:
            messages.warning(request, f'{symbol} is not in your portfolio.')
            return redirect('portfolio')
        
        # Delete the portfolio entry
        portfolio_item.delete()
        
        messages.success(request, f'{symbol} has been removed from your portfolio.')
        return redirect('portfolio')
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.warning(f"Database error: {e}")
        messages.error(request, 'An error occurred. Please try again.')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error deleting portfolio stock: {e}", exc_info=True)
        messages.error(request, 'An error occurred while removing the stock from your portfolio.')
        return redirect('portfolio')


@login_required
def import_wealthsimple_csv(request):
    """Import transactions from Wealthsimple CSV export"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        import io
        
        if request.method == 'POST':
            if 'csv_file' not in request.FILES:
                messages.error(request, 'Please select a CSV file to upload.')
                return redirect('import_wealthsimple_csv')
            
            csv_file = request.FILES['csv_file']
            
            # Check file extension
            if not csv_file.name.endswith('.csv'):
                messages.error(request, 'Please upload a CSV file.')
                return redirect('import_wealthsimple_csv')
            
            # Read CSV file with encoding detection
            try:
                # Read file content
                file_content = csv_file.read()
                
                # Try to detect encoding (optional - chardet may not be installed)
                encoding = 'utf-8'
                try:
                    import chardet
                    detected = chardet.detect(file_content)
                    if detected and detected.get('encoding'):
                        encoding = detected.get('encoding')
                except ImportError:
                    # chardet not installed, use default
                    pass
                except Exception:
                    # Detection failed, use default
                    pass
                
                # Try multiple encodings
                decoded_file = None
                for enc in [encoding, 'utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']:
                    try:
                        decoded_file = file_content.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                
                if decoded_file is None:
                    messages.error(request, 'Could not decode CSV file. Please ensure it is a valid CSV file.')
                    return redirect('import_wealthsimple_csv')
                
                # Handle BOM (Byte Order Mark) if present
                if decoded_file.startswith('\ufeff'):
                    decoded_file = decoded_file[1:]
                
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)
                
                # Check if we have any rows
                if not reader.fieldnames:
                    messages.error(request, 'CSV file appears to be empty or invalid.')
                    return redirect('import_wealthsimple_csv')
                
                # Log available columns for debugging
                logger.info(f"CSV columns detected: {reader.fieldnames}")
                
                # Detect CSV format - check if this is Wealthsimple statement format
                row_lower_headers = {k.lower().strip(): k for k in reader.fieldnames if k}
                is_statement_format = 'description' in row_lower_headers and 'transaction' in row_lower_headers
                
                imported_count = 0
                skipped_count = 0
                errors = []
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 because row 1 is header
                    try:
                        # Skip empty rows
                        if not any(row.values()):
                            continue
                        
                        # Case-insensitive column matching
                        row_lower = {k.lower().strip(): v for k, v in row.items() if k}
                        
                        # Handle Wealthsimple statement format
                        if is_statement_format:
                            date_str = row_lower.get('date', '').strip() if 'date' in row_lower else None
                            transaction_code = row_lower.get('transaction', '').strip().upper() if 'transaction' in row_lower else None
                            description = row_lower.get('description', '').strip() if 'description' in row_lower else ''
                            amount_str = row_lower.get('amount', '').strip() if 'amount' in row_lower else '0'
                            currency = row_lower.get('currency', 'CAD').strip().upper() if 'currency' in row_lower else 'CAD'
                            
                            # Skip non-trade transactions
                            skip_transactions = ['LOAN', 'RECALL', 'FPLINT']  # Stock lending transactions
                            if transaction_code in skip_transactions:
                                skipped_count += 1
                                continue
                            
                            # Skip if no date or transaction code
                            if not date_str or not transaction_code:
                                continue
                            
                            # Parse description to extract symbol and quantity
                            symbol = None
                            quantity = None
                            
                            # Pattern: "SYMBOL - Company Name: X.XXXX Shares..."
                            # Or: "SYMBOL - Company Name: X.XXXX Shares on loan"
                            symbol_match = re.search(r'^([A-Z0-9\.]+)\s*-\s*', description, re.IGNORECASE)
                            if symbol_match:
                                symbol = symbol_match.group(1).upper().strip()
                            
                            # Extract quantity from description
                            # Pattern: "X.XXXX Shares" or "X.XXXX shares"
                            qty_match = re.search(r'(\d+\.?\d*)\s+shares?', description, re.IGNORECASE)
                            if qty_match:
                                quantity = qty_match.group(1)
                            
                            # Map transaction codes to our transaction types
                            transaction_type_mapping = {
                                'BUY': 'BUY',
                                'SELL': 'SELL',
                                'DIV': 'DIVIDEND',
                                'STKDIV': 'DIVIDEND',
                                'STKDIS': 'DIVIDEND',  # Stock distribution
                                'NCDIS': 'DIVIDEND',   # Non-cash distribution
                                'ROC': 'DIVIDEND',     # Return of capital (treat as dividend)
                            }
                            
                            trans_type = transaction_type_mapping.get(transaction_code)
                            
                            # Skip if we can't map the transaction type or don't have symbol
                            if not trans_type or not symbol:
                                skipped_count += 1
                                continue
                            
                            # For dividends, if no quantity, set to 0 (cash dividend)
                            if trans_type == 'DIVIDEND' and not quantity:
                                quantity = '0'
                            
                            # For BUY/SELL, we need quantity
                            if trans_type in ['BUY', 'SELL'] and not quantity:
                                errors.append(f"Row {row_num}: Cannot extract quantity from description: '{description}'")
                                continue
                            
                            # Calculate price from amount and quantity
                            price = None
                            try:
                                amount = float(amount_str.replace(',', '').replace('$', '').strip() or '0')
                                qty = float(quantity.replace(',', '').strip() or '0')
                                
                                if trans_type == 'DIVIDEND':
                                    # For dividends, amount is the dividend payment
                                    # We'll use a price of 0 and store amount in notes
                                    price = '0'
                                    quantity = '0'  # Cash dividend, no shares
                                elif qty > 0:
                                    # Price per share = total amount / quantity
                                    price = str(abs(amount / qty))
                                else:
                                    errors.append(f"Row {row_num}: Invalid quantity: {quantity}")
                                    continue
                            except (ValueError, ZeroDivisionError) as e:
                                errors.append(f"Row {row_num}: Could not calculate price from amount '{amount_str}' and quantity '{quantity}': {e}")
                                continue
                            
                            fees = '0'  # Wealthsimple doesn't charge fees for trades
                            
                        else:
                            # Original format: Date, Symbol, Type, Quantity, Price, Fees
                            date_str = None
                            symbol = None
                            trans_type = None
                            quantity = None
                            price = None
                            fees = '0'
                            
                            # Date
                            for key in ['date', 'transaction date', 'transaction_date', 'trade date', 'trade_date']:
                                if key in row_lower and row_lower[key]:
                                    date_str = row_lower[key].strip()
                                    break
                            
                            # Symbol
                            for key in ['symbol', 'stock', 'ticker', 'security', 'instrument']:
                                if key in row_lower and row_lower[key]:
                                    symbol = row_lower[key].strip()
                                    break
                            
                            # Type
                            for key in ['type', 'transaction type', 'transaction_type', 'action', 'side']:
                                if key in row_lower and row_lower[key]:
                                    trans_type = row_lower[key].strip()
                                    break
                            
                            # Quantity/Shares
                            for key in ['quantity', 'shares', 'qty', 'amount', 'units']:
                                if key in row_lower and row_lower[key]:
                                    quantity = row_lower[key].strip()
                                    break
                            
                            # Price
                            for key in ['price', 'price per share', 'price_per_share', 'unit price', 'unit_price', 'cost']:
                                if key in row_lower and row_lower[key]:
                                    price = row_lower[key].strip()
                                    break
                            
                            # Fees
                            for key in ['fees', 'commission', 'fee', 'charges']:
                                if key in row_lower and row_lower[key]:
                                    fees = row_lower[key].strip() or '0'
                                    break
                            
                            # Validate required fields
                            if not all([date_str, symbol, trans_type, quantity, price]):
                                missing = []
                                if not date_str: missing.append('Date')
                                if not symbol: missing.append('Symbol')
                                if not trans_type: missing.append('Type')
                                if not quantity: missing.append('Quantity')
                                if not price: missing.append('Price')
                                errors.append(f"Row {row_num}: Missing fields: {', '.join(missing)}. Available columns: {', '.join(reader.fieldnames)}")
                                continue
                            
                            # Map transaction type (case-insensitive)
                            type_mapping = {
                                'buy': 'BUY',
                                'sell': 'SELL',
                                'dividend': 'DIVIDEND',
                                'purchase': 'BUY',
                                'sale': 'SELL',
                                'deposit': 'BUY',
                                'withdrawal': 'SELL',
                            }
                            trans_type = type_mapping.get(trans_type.lower().strip(), 'BUY')
                        
                        # Parse date - try multiple formats
                        if not date_str:
                            continue
                        
                        transaction_date = None
                        date_formats = [
                            '%Y-%m-%d',
                            '%m/%d/%Y',
                            '%d/%m/%Y',
                            '%Y/%m/%d',
                            '%m-%d-%Y',
                            '%d-%m-%Y',
                            '%Y-%m-%d %H:%M:%S',
                            '%m/%d/%Y %H:%M:%S',
                        ]
                        
                        for date_format in date_formats:
                            try:
                                transaction_date = datetime.strptime(date_str.strip(), date_format).date()
                                break
                            except ValueError:
                                continue
                        
                        if transaction_date is None:
                            errors.append(f"Row {row_num}: Could not parse date '{date_str}'. Supported formats: YYYY-MM-DD, MM/DD/YYYY")
                            continue
                        
                        # Parse date - try multiple formats
                        transaction_date = None
                        date_formats = [
                            '%Y-%m-%d',
                            '%m/%d/%Y',
                            '%d/%m/%Y',
                            '%Y/%m/%d',
                            '%m-%d-%Y',
                            '%d-%m-%Y',
                            '%Y-%m-%d %H:%M:%S',
                            '%m/%d/%Y %H:%M:%S',
                        ]
                        
                        for date_format in date_formats:
                            try:
                                transaction_date = datetime.strptime(date_str.strip(), date_format).date()
                                break
                            except ValueError:
                                continue
                        
                        if transaction_date is None:
                            errors.append(f"Row {row_num}: Could not parse date '{date_str}'. Supported formats: YYYY-MM-DD, MM/DD/YYYY")
                            continue
                        
                        # Get or create stock
                        symbol_upper = symbol.upper().strip()
                        stock, created = Stock.objects.get_or_create(
                            symbol=symbol_upper,
                            defaults={'code': symbol_upper, 'company_name': symbol_upper}
                        )
                        
                        # Parse numeric values - handle commas and currency symbols
                        try:
                            quantity_clean = quantity.replace(',', '').replace('$', '').strip()
                            price_clean = price.replace(',', '').replace('$', '').strip()
                            fees_clean = fees.replace(',', '').replace('$', '').strip() if fees else '0'
                            
                            shares = float(quantity_clean)
                            price_per_share = float(price_clean)
                            fees_amount = float(fees_clean) if fees_clean else 0.0
                            
                            # For dividends, shares can be 0 (cash dividend)
                            if trans_type == 'DIVIDEND':
                                if shares < 0:
                                    errors.append(f"Row {row_num}: Invalid shares value for dividend: {shares}")
                                    continue
                            elif shares <= 0 or price_per_share < 0:
                                errors.append(f"Row {row_num}: Invalid values - shares: {shares}, price: {price_per_share}")
                                continue
                        except ValueError as e:
                            errors.append(f"Row {row_num}: Could not parse numeric values - Quantity: '{quantity}', Price: '{price}', Fees: '{fees}'")
                            continue
                        
                        # Build notes
                        notes = "Imported from Wealthsimple CSV"
                        if is_statement_format and description:
                            notes = f"Imported from Wealthsimple CSV: {description}"
                        
                        # Create transaction
                        transaction = Transaction.objects.create(
                            user=request.user,
                            stock=stock,
                            transaction_type=trans_type,
                            transaction_date=transaction_date,
                            shares=shares,
                            price_per_share=price_per_share,
                            fees=fees_amount,
                            notes=notes
                        )
                        
                        # For sell transactions, calculate realized gain/loss
                        if trans_type == 'SELL':
                            try:
                                cost_basis, transactions_used, error = TransactionService.calculate_cost_basis(
                                    request.user, stock, shares, 'FIFO'
                                )
                                if error:
                                    transaction.realized_gain_loss = None
                                else:
                                    if cost_basis is not None:
                                        transaction.calculate_realized_gain_loss(cost_basis)
                                    else:
                                        transaction.realized_gain_loss = None
                                transaction.save()
                            except Exception as e:
                                logger.warning(f"Could not calculate cost basis for row {row_num}: {e}", exc_info=True)
                                transaction.realized_gain_loss = None
                                transaction.save()
                                # Continue anyway - transaction is created
                        
                        imported_count += 1
                        
                    except Exception as e:
                        error_msg = f"Row {row_num}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(f"Error importing row {row_num}: {e}", exc_info=True)
                
                # Update portfolio for all affected stocks
                if imported_count > 0:
                    try:
                        affected_stocks = Transaction.objects.filter(
                            user=request.user,
                            transaction_date__gte=timezone.now().date() - timedelta(days=365)
                        ).values_list('stock', flat=True).distinct()
                        
                        for stock_id in affected_stocks:
                            try:
                                stock = Stock.objects.get(id=stock_id)
                                TransactionService.update_portfolio_from_transactions(request.user, stock)
                            except Exception as e:
                                logger.error(f"Error updating portfolio for stock {stock_id}: {e}")
                    except Exception as e:
                        logger.error(f"Error updating portfolios: {e}")
                
                # Show results
                if imported_count > 0:
                    success_msg = f'Successfully imported {imported_count} transaction(s)!'
                    if skipped_count > 0:
                        success_msg += f' ({skipped_count} non-trade transaction(s) skipped: LOAN, RECALL, FPLINT, etc.)'
                    messages.success(request, success_msg)
                else:
                    if skipped_count > 0:
                        messages.warning(request, f'No transactions were imported. {skipped_count} row(s) were skipped (non-trade transactions). Please ensure your CSV contains BUY, SELL, or DIV transactions.')
                    else:
                        messages.warning(request, 'No transactions were imported. Please check your CSV format.')
                
                if errors:
                    error_summary = f'{len(errors)} error(s) occurred. '
                    if len(errors) <= 5:
                        error_summary += 'Errors: ' + '; '.join(errors[:5])
                    else:
                        error_summary += f'First 5 errors: ' + '; '.join(errors[:5]) + f' (and {len(errors)-5} more)'
                    messages.warning(request, error_summary)
                
                return redirect('transactions_list')
                
            except csv.Error as e:
                logger.error(f"CSV parsing error: {e}")
                messages.error(request, f'CSV parsing error: {str(e)}. Please ensure your file is a valid CSV.')
                return redirect('import_wealthsimple_csv')
            except Exception as e:
                logger.error(f"Error reading CSV file: {e}", exc_info=True)
                messages.error(request, f'Error reading CSV file: {str(e)}. Please check the file format and try again.')
                return redirect('import_wealthsimple_csv')
        
        return render(request, 'transactions/import.html')
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.warning(f"Transaction table not found: {e}")
        messages.error(request, 'Transaction feature is not available yet. Please run migrations.')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error in import_wealthsimple_csv: {e}", exc_info=True)
        messages.error(request, f'An error occurred: {str(e)}')
        return redirect('transactions_list')


@login_required
def export_transactions(request):
    """Export transactions to CSV for tax purposes"""
    try:
        from django.db import DatabaseError, ProgrammingError, OperationalError
        
        year = request.GET.get('year', timezone.now().year)
        symbol = request.GET.get('symbol', None)
        
        transactions = Transaction.objects.filter(user=request.user).select_related('stock').order_by('transaction_date', 'created_at')
        
        if year:
            transactions = transactions.filter(transaction_date__year=year)
        
        if symbol:
            stock = get_object_or_404(Stock, symbol=symbol.upper())
            transactions = transactions.filter(stock=stock)
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="transactions_{year}_{request.user.username}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Date', 'Symbol', 'Type', 'Shares', 'Price per Share', 'Fees',
            'Total Amount', 'Realized Gain/Loss', 'Cost Basis Method', 'Notes'
        ])
        
        for transaction in transactions:
            writer.writerow([
                transaction.transaction_date.strftime('%Y-%m-%d'),
                transaction.stock.symbol,
                transaction.get_transaction_type_display(),
                f"{transaction.shares:.6f}",
                f"{transaction.price_per_share:.4f}",
                f"{transaction.fees:.2f}",
                f"{transaction.total_amount:.2f}",
                f"{transaction.realized_gain_loss:.2f}" if transaction.realized_gain_loss else '',
                transaction.get_cost_basis_method_display(),
                transaction.notes
            ])
        
        return response
    except (ProgrammingError, OperationalError, DatabaseError) as e:
        logger.warning(f"Transaction table not found: {e}")
        messages.error(request, 'Transaction feature is not available yet. Please run migrations: python manage.py migrate')
        return redirect('portfolio')
    except Exception as e:
        logger.error(f"Error exporting transactions: {e}", exc_info=True)
        messages.error(request, f'An error occurred while exporting transactions: {str(e)}')
        return redirect('transactions_list')


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
        
        # If no dividends from user's portfolio, show general upcoming dividends
        if not upcoming_dividends:
            general_dividends = StockService.get_upcoming_dividends(days=30, limit=3)
            upcoming_dividends = [
                {
                    'stock': dividend.stock,
                    'amount': dividend.amount,
                    'ex_dividend_date': dividend.ex_dividend_date,
                    'days_until': (dividend.ex_dividend_date - today).days
                }
                for dividend in general_dividends
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
        sector_allocation = {}
        for item in portfolio_items:
            if item.stock.sector:
                sectors.add(item.stock.sector)
                if item.latest_price_value and item.shares_owned:
                    sector_value = float(item.latest_price_value * item.shares_owned)
                    sector_allocation[item.stock.sector] = sector_allocation.get(item.stock.sector, 0) + sector_value
        sectors_count = len(sectors)
        
        # Calculate top performers and worst performers
        top_performers = []
        worst_performers = []
        for item in portfolio_items:
            if item.latest_price_value and item.average_cost and item.shares_owned:
                current_value = float(item.latest_price_value * item.shares_owned)
                cost_basis = float(item.average_cost * item.shares_owned)
                gain_loss = current_value - cost_basis
                gain_percent = (gain_loss / cost_basis * 100) if cost_basis > 0 else 0
                
                performer_data = {
                    'stock': item.stock,
                    'gain_loss': gain_loss,
                    'gain_percent': gain_percent,
                    'current_value': current_value,
                }
                
                if gain_percent > 0:
                    top_performers.append(performer_data)
                elif gain_percent < 0:
                    worst_performers.append(performer_data)
        
        # Sort and limit
        top_performers = sorted(top_performers, key=lambda x: x['gain_percent'], reverse=True)[:3]
        worst_performers = sorted(worst_performers, key=lambda x: x['gain_percent'])[:3]
        
        # Calculate sector allocation percentages and sort by value
        sector_allocation_percent = {}
        if total_value > 0:
            for sector, value in sector_allocation.items():
                sector_allocation_percent[sector] = (value / total_value) * 100
        
        # Sort sectors by percentage (descending) for display
        sector_allocation_sorted = sorted(
            sector_allocation_percent.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]  # Top 5 sectors
        
        # Get recent news for portfolio and watchlist stocks (last 7 days)
        portfolio_stock_ids = [item.stock.id for item in portfolio_items]
        watchlist_stock_ids = [item.stock.id for item in watchlist_items]
        all_stock_ids = list(set(portfolio_stock_ids + watchlist_stock_ids))
        
        # If no portfolio or watchlist stocks, fallback to upcoming dividend stocks (next 15 days)
        if not all_stock_ids:
            today = timezone.now().date()
            fifteen_days_later = today + timedelta(days=15)
            upcoming_dividend_stocks = Stock.objects.filter(
                dividends__ex_dividend_date__gte=today,
                dividends__ex_dividend_date__lte=fifteen_days_later
            ).distinct()
            all_stock_ids = list(upcoming_dividend_stocks.values_list('id', flat=True))
        
        cutoff_date = timezone.now() - timedelta(days=7)
        recent_news = StockNews.objects.filter(
            stock_id__in=all_stock_ids,
            published_at__gte=cutoff_date
        ).select_related('stock').order_by('-published_at')[:5]
        
        # Get real performance data from snapshots (only if model exists)
        # Limit query to avoid timeout - only get last 30 days for faster response
        performance_snapshots = None
        try:
            performance_snapshots = PortfolioService.get_portfolio_performance_history(request.user, days=30)
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
        # Limit to last 30 days to avoid timeout
        performance_data = []
        if performance_snapshots is not None:
            try:
                if hasattr(performance_snapshots, 'exists') and performance_snapshots.exists():
                    # Get last 30 days of data (reduced from 180 to avoid timeout)
                    thirty_days_ago = timezone.now().date() - timedelta(days=30)
                    recent_snapshots = list(performance_snapshots.filter(snapshot_date__gte=thirty_days_ago)[:6])
                    
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
        
        # Create portfolio snapshot for today (if not exists) - run in background to avoid timeout
        # Only create if PortfolioSnapshot model exists (migration has been run)
        import threading
        def create_snapshot_async():
            try:
                from portfolio.models import PortfolioSnapshot
                PortfolioService.create_portfolio_snapshot(request.user)
            except (ImportError, Exception) as e:
                # Model doesn't exist yet or other error - skip snapshot creation
                logger.debug(f"Could not create portfolio snapshot (model may not exist yet): {e}")
        
        # Start snapshot creation in background thread (non-blocking)
        snapshot_thread = threading.Thread(target=create_snapshot_async, daemon=True)
        snapshot_thread.start()
        
        # Get affiliate links and sponsored content for dashboard
        from portfolio.models import AffiliateLink, SponsoredContent
        import random
        
        affiliate_links = AffiliateLink.objects.filter(is_active=True).order_by('display_order')[:3]
        
        # Get all active sponsored content and randomly select 2
        all_sponsored = SponsoredContent.objects.filter(
            is_active=True,
            content_type__in=['featured_stock', 'educational', 'promotion']
        ).order_by('display_order')
        sponsored_content = [c for c in all_sponsored if c.is_currently_active()]
        
        # Randomly select 2 sponsored items (or all if less than 2)
        if len(sponsored_content) > 2:
            sponsored_content = random.sample(sponsored_content, 2)
        # If 2 or less, show all
        
        # Track views for sponsored content
        for content in sponsored_content:
            content.track_view()
        
        context = {
            'portfolio_items': portfolio_items,
            'affiliate_links': affiliate_links,
            'sponsored_content': sponsored_content,
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
            'top_performers': top_performers,
            'worst_performers': worst_performers,
            'sector_allocation': sector_allocation_percent,
            'sector_allocation_sorted': sector_allocation_sorted,
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
    
    # Calculate dividend income based on portfolio holdings
    dividend_income_calculation = None
    portfolio_item_for_calc = None
    if request.user.is_authenticated:
        portfolio_item_for_calc = UserPortfolio.objects.filter(user=request.user, stock=stock).first()
        if portfolio_item_for_calc and portfolio_item_for_calc.shares_owned and dividend and dividend.amount:
            shares = float(portfolio_item_for_calc.shares_owned)
            div_amount = float(dividend.amount)
            
            # Calculate based on frequency
            if dividend.frequency:
                if 'Monthly' in dividend.frequency:
                    annual_income = div_amount * 12 * shares
                    quarterly_income = div_amount * 3 * shares
                elif 'Quarterly' in dividend.frequency:
                    annual_income = div_amount * 4 * shares
                    quarterly_income = div_amount * shares
                elif 'Semi-Annual' in dividend.frequency:
                    annual_income = div_amount * 2 * shares
                    quarterly_income = div_amount * shares / 2
                elif 'Annual' in dividend.frequency:
                    annual_income = div_amount * shares
                    quarterly_income = div_amount * shares / 4
                else:
                    annual_income = div_amount * 4 * shares  # Default to quarterly
                    quarterly_income = div_amount * shares
                
                dividend_income_calculation = {
                    'shares': shares,
                    'per_payment': div_amount * shares,
                    'annual': annual_income,
                    'quarterly': quarterly_income,
                }
    
    # Get alert statistics
    alert_stats = None
    if alert:
        # Count how many times this alert would have fired (based on past dividends)
        today = timezone.now().date()
        past_dividends = Dividend.objects.filter(
            stock=stock,
            ex_dividend_date__lte=today,
            ex_dividend_date__isnull=False
        ).order_by('-ex_dividend_date')[:12]  # Last 12 dividends
        
        alert_stats = {
            'total_past_dividends': past_dividends.count(),
            'alert_created_date': alert.created_at if hasattr(alert, 'created_at') else None,
        }
    
    context = {
        'stock': stock,
        'dividend': dividend,
        'alert': alert,
        'dividend_income_calculation': dividend_income_calculation,
        'alert_stats': alert_stats,
        'current_alert_count': DividendAlert.objects.filter(user=request.user).count(),
        'max_alerts': AlertService.MAX_DIVIDEND_ALERTS,
        'today': timezone.now().date(),
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
    
    # Check if this is an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'success',
            'is_active': existing_alert.is_active if existing_alert else True,
            'message': f'Dividend alerts for {stock.symbol} have been {"enabled" if (existing_alert and existing_alert.is_active) or not existing_alert else "disabled"}.'
        })
    
    return redirect('stock_detail', symbol=symbol)


@login_required
@require_http_methods(["POST"])
def toggle_alert_status(request, alert_id):
    """Toggle alert active status by alert ID - for use from alerts page"""
    try:
        alert = get_object_or_404(DividendAlert, id=alert_id, user=request.user)
        alert.is_active = not alert.is_active
        alert.save()
        
        status = "enabled" if alert.is_active else "disabled"
        
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'is_active': alert.is_active,
                'message': f'Alert for {alert.stock.symbol} has been {status}.'
            })
        
        messages.success(request, f'Alert for {alert.stock.symbol} has been {status}.')
        return redirect('my_alerts')
        
    except Exception as e:
        logger.error(f"Error toggling alert status: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': 'An error occurred while updating the alert.'
            }, status=500)
        
        messages.error(request, 'An error occurred while updating the alert.')
        return redirect('my_alerts')

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
        
        # Get upcoming alerts (next 7 days)
        upcoming_alerts_7d = [a for a in alerts_data if a['days_until'] is not None and 0 <= a['days_until'] <= 7 and a['alert'].is_active]
        
        # Get total dividend amount from upcoming alerts
        total_upcoming_dividend = sum(
            float(a['latest_dividend'].amount) for a in alerts_data 
            if a['latest_dividend'] and a['days_until'] is not None and a['days_until'] >= 0 and a['alert'].is_active
        )
        
        # Get recent news for alert stocks
        from portfolio.models import StockNews
        alert_stocks = [a['alert'].stock for a in alerts_data]
        recent_news = StockNews.objects.filter(
            stock__in=alert_stocks
        ).select_related('stock').order_by('-published_at')[:5]
        
        # Calculate insights
        high_yield_stocks = [a for a in alerts_data if a['latest_dividend'] and float(a['latest_dividend'].yield_percent or 0) > 5]
        urgent_alerts = [a for a in alerts_data if a['days_until'] is not None and 0 <= a['days_until'] <= 3 and a['alert'].is_active]
        
        context = {
            'alerts': alerts_data,
            'active_alerts_count': active_alerts_count,
            'upcoming_alerts_count': upcoming_alerts_count,
            'upcoming_alerts_7d': upcoming_alerts_7d,
            'total_upcoming_dividend': total_upcoming_dividend,
            'recent_news': recent_news,
            'high_yield_stocks': high_yield_stocks,
            'urgent_alerts': urgent_alerts,
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
    Runs in background thread to avoid timeout issues
    """
    import threading
    
    # Simple authentication (customize as needed)
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to trigger dividend alerts from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    # Check if dry run is requested
    dry_run = request.POST.get('dry_run', '').lower() == 'true'
    
    try:
        # Run the management command in background thread to avoid timeout
        def run_alerts():
            try:
                logger.info(f"Starting dividend alerts processing (dry_run={dry_run})")
                call_command('send_dividend_alerts', dry_run=dry_run)
                logger.info(f"Dividend alerts processing completed")
            except Exception as e:
                logger.error(f"Error in dividend alerts processing: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Start background thread
        thread = threading.Thread(target=run_alerts, daemon=True)
        thread.start()
        
        # Return immediately to avoid timeout
        return JsonResponse({
            'status': 'accepted', 
            'message': f'Dividend alerts processing started in background (dry_run={dry_run})',
            'dry_run': dry_run,
            'note': 'Alerts are being processed asynchronously. Check logs for progress.'
        })
        
    except Exception as e:
        logger.error(f"Error triggering dividend alerts: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({
            'status': 'error', 
            'message': f'Error: {str(e)}'
        }, status=500)

@csrf_exempt
@require_POST
def trigger_daily_scrape(request):
    """
    API endpoint to trigger daily stock scraping
    Runs asynchronously to avoid Render.com timeout issues
    CSRF exempt - uses secret key authentication instead
    """
    import threading
    from portfolio.models import ScrapeStatus
    
    # Simple authentication
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to trigger daily scrape from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    # Check if scraping is already running
    running_scrape = ScrapeStatus.get_running()
    if running_scrape:
        return JsonResponse({
            'status': 'busy',
            'message': 'Scraping is already running',
            'started_at': running_scrape.started_at.isoformat() if running_scrape.started_at else None,
            'days': running_scrape.days,
            'status_id': running_scrape.id
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
        
        # Create new scrape status
        scrape_status = ScrapeStatus.create_new(days=days)
        
        # Run scraping in background thread to avoid timeout
        def run_scrape():
            try:
                logger.info(f"🚀 Starting background scrape for {days} days (Status ID: {scrape_status.id})")
                call_command('daily_scrape', days=days, status_id=scrape_status.id)
                logger.info(f"✅ Background scrape completed (Status ID: {scrape_status.id})")
            except Exception as e:
                logger.error(f"❌ Error in background scrape (Status ID: {scrape_status.id}): {e}")
                # Status will be marked as failed by the command itself
        
        # Start background thread
        thread = threading.Thread(target=run_scrape, daemon=True)
        thread.start()
        
        # Return immediately to avoid timeout
        return JsonResponse({
            'status': 'accepted', 
            'message': f'Daily stock scrape started in background for {days} days',
            'days': days,
            'started_at': scrape_status.started_at.isoformat() if scrape_status.started_at else None,
            'status_id': scrape_status.id,
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
    Similar to trigger_daily_scrape - runs asynchronously to avoid timeout
    CSRF exempt - uses secret key authentication instead
    
    Parameters:
    - secret_key: Authentication key (required)
    - dry_run: Test run without sending emails (optional, boolean, default: false)
    - user: Send to specific user only (optional, username)
    - frequency: Filter by subscription frequency (optional: weekly, biweekly, monthly)
    - force: Force send even if recently sent (optional, boolean, default: false)
    """
    import threading
    from django.core.management import call_command
    from portfolio.models import NewsletterSubscription
    
    # Simple authentication
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to trigger newsletter from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        # Get optional parameters
        dry_run = request.POST.get('dry_run', '').lower() == 'true'
        user = request.POST.get('user', '').strip()
        frequency = request.POST.get('frequency', '').strip().lower()
        force = request.POST.get('force', '').lower() == 'true'
        
        # Validate frequency if provided
        valid_frequencies = ['weekly', 'biweekly', 'monthly']
        if frequency and frequency not in valid_frequencies:
            return JsonResponse({
                'status': 'error',
                'message': f'Invalid frequency. Must be one of: {", ".join(valid_frequencies)}'
            }, status=400)
        
        # Get subscriber count for response
        subscribers_query = NewsletterSubscription.objects.filter(is_active=True)
        if user:
            from django.contrib.auth.models import User
            try:
                user_obj = User.objects.get(username=user)
                subscribers_query = subscribers_query.filter(user=user_obj)
            except User.DoesNotExist:
                return JsonResponse({
                    'status': 'error',
                    'message': f'User "{user}" not found'
                }, status=404)
        
        if frequency:
            subscribers_query = subscribers_query.filter(frequency=frequency)
        
        subscriber_count = subscribers_query.count()
        
        # Build command arguments
        cmd_options = {}
        if dry_run:
            cmd_options['dry_run'] = True
        
        # Run newsletter sending in background thread to avoid timeout
        def run_newsletter():
            try:
                logger.info(f"🚀 Starting background newsletter sending (dry_run={dry_run}, user={user or 'all'}, frequency={frequency or 'all'})")
                
                # If specific user, we need to handle differently
                if user:
                    from portfolio.utils.newsletter_utils import DividendNewsletterGenerator
                    from portfolio.utils.newsletter_email import send_newsletter_email
                    from django.contrib.auth.models import User
                    
                    user_obj = User.objects.get(username=user)
                    subscription = NewsletterSubscription.objects.filter(user=user_obj, is_active=True).first()
                    
                    if subscription:
                        generator = DividendNewsletterGenerator()
                        newsletter_content = generator.generate_newsletter_content(user=user_obj)
                        
                        if dry_run:
                            logger.info(f"[DRY RUN] Would send newsletter to {user_obj.email}")
                        else:
                            success = send_newsletter_email(user_obj, newsletter_content)
                            if success:
                                subscription.last_sent = timezone.now()
                                subscription.save(update_fields=['last_sent'])
                                logger.info(f"Newsletter sent to {user_obj.email}")
                    else:
                        logger.warning(f"User {user} does not have an active newsletter subscription")
                else:
                    # Use management command for bulk sending
                    call_command('send_dividend_newsletter', **cmd_options)
                
                logger.info(f"✅ Background newsletter sending completed")
            except Exception as e:
                logger.error(f"❌ Error in background newsletter sending: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Start background thread
        thread = threading.Thread(target=run_newsletter, daemon=True)
        thread.start()
        
        # Build response
        response_data = {
            'status': 'accepted',
            'message': f'Newsletter sending started in background',
            'dry_run': dry_run,
            'subscribers_count': subscriber_count,
            'note': 'Newsletter is being sent asynchronously. Check logs for progress.'
        }
        
        if user:
            response_data['user'] = user
        if frequency:
            response_data['frequency'] = frequency
        if force:
            response_data['force'] = True
        
        return JsonResponse(response_data)
        
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
    Returns the latest scrape status from database
    """
    from portfolio.models import ScrapeStatus, StockPrice, Stock
    from django.utils import timezone
    
    # Get latest scrape status
    latest_status = ScrapeStatus.get_latest()
    running_status = ScrapeStatus.get_running()
    
    # Get recent stock price updates (today)
    recent_updates = StockPrice.objects.filter(
        price_date=timezone.now().date()
    ).count()
    
    # Get total stocks
    total_stocks = Stock.objects.count()
    
    # Build status data
    if latest_status:
        status_data = {
            'status_id': latest_status.id,
            'status': latest_status.status,
            'is_running': latest_status.is_running,
            'started_at': latest_status.started_at.isoformat() if latest_status.started_at else None,
            'completed_at': latest_status.completed_at.isoformat() if latest_status.completed_at else None,
            'days': latest_status.days,
            'total_stocks': latest_status.total_stocks,
            'success_count': latest_status.success_count,
            'failed_count': latest_status.failed_count,
            'success_rate': latest_status.success_rate,
            'duration_seconds': latest_status.duration_seconds,
            'duration_minutes': latest_status.duration_minutes,
            'error_message': latest_status.error_message,
            'failed_symbols': latest_status.failed_symbols[:10] if latest_status.failed_symbols else [],  # Limit to 10
            'notes': latest_status.notes,
            'database_stats': {
                'total_stocks': total_stocks,
                'stocks_updated_today': recent_updates,
            }
        }
        
        # If running, calculate current duration
        if latest_status.is_running and latest_status.started_at:
            current_duration = (timezone.now() - latest_status.started_at).total_seconds()
            status_data['current_duration_seconds'] = int(current_duration)
            status_data['current_duration_minutes'] = round(current_duration / 60, 1)
    else:
        # No scrape status found
        status_data = {
            'status': 'no_data',
            'is_running': False,
            'message': 'No scrape status found in database',
            'database_stats': {
                'total_stocks': total_stocks,
                'stocks_updated_today': recent_updates,
            }
        }
    
    # Add running status info if different from latest
    if running_status and (not latest_status or running_status.id != latest_status.id):
        status_data['running_status_id'] = running_status.id
        status_data['running_started_at'] = running_status.started_at.isoformat() if running_status.started_at else None
    
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
    """Display news for stocks in user's portfolio, or upcoming dividend stocks if no portfolio"""
    # Get user's portfolio stocks
    portfolio_stocks = Stock.objects.filter(
        userportfolio__user=request.user
    ).distinct()
    
    # If no portfolio stocks, fallback to upcoming dividend stocks (next 15 days)
    if not portfolio_stocks.exists():
        today = timezone.now().date()
        fifteen_days_later = today + timedelta(days=15)
        portfolio_stocks = Stock.objects.filter(
            dividends__ex_dividend_date__gte=today,
            dividends__ex_dividend_date__lte=fifteen_days_later
        ).distinct()
        show_upcoming_dividends = True
    else:
        show_upcoming_dividends = False
    
    # Get recent news (last 7 days)
    cutoff_date = timezone.now() - timedelta(days=7)
    news_items = StockNews.objects.filter(
        stock__in=portfolio_stocks,
        published_at__gte=cutoff_date
    ).select_related('stock').order_by('-published_at')
    
    # Paginate - show 20 articles per page
    paginator = Paginator(news_items, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Group by stock for display
    news_by_stock = {}
    for news in page_obj:
        symbol = news.stock.symbol
        if symbol not in news_by_stock:
            news_by_stock[symbol] = {
                'stock': news.stock,
                'articles': []
            }
        news_by_stock[symbol]['articles'].append(news)
    
    context = {
        'news_by_stock': news_by_stock,
        'news_items': page_obj,  # For pagination controls
        'total_articles': news_items.count(),
        'portfolio_stocks_count': portfolio_stocks.count(),
        'show_upcoming_dividends': show_upcoming_dividends,
    }
    
    return render(request, 'portfolio_news.html', context)


@login_required
def watchlist_news(request):
    """Display news for stocks in user's watchlist, or upcoming dividend stocks if no watchlist"""
    # Get user's watchlist stocks
    watchlist_stocks = Stock.objects.filter(
        watchlist__user=request.user
    ).distinct()
    
    # If no watchlist stocks, fallback to upcoming dividend stocks (next 15 days)
    if not watchlist_stocks.exists():
        today = timezone.now().date()
        fifteen_days_later = today + timedelta(days=15)
        watchlist_stocks = Stock.objects.filter(
            dividends__ex_dividend_date__gte=today,
            dividends__ex_dividend_date__lte=fifteen_days_later
        ).distinct()
        show_upcoming_dividends = True
    else:
        show_upcoming_dividends = False
    
    # Get recent news (last 7 days)
    cutoff_date = timezone.now() - timedelta(days=7)
    news_items = StockNews.objects.filter(
        stock__in=watchlist_stocks,
        published_at__gte=cutoff_date
    ).select_related('stock').order_by('-published_at')
    
    # Paginate - show 20 articles per page
    paginator = Paginator(news_items, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Group by stock for display
    news_by_stock = {}
    for news in page_obj:
        symbol = news.stock.symbol
        if symbol not in news_by_stock:
            news_by_stock[symbol] = {
                'stock': news.stock,
                'articles': []
            }
        news_by_stock[symbol]['articles'].append(news)
    
    context = {
        'news_by_stock': news_by_stock,
        'news_items': page_obj,  # For pagination controls
        'total_articles': news_items.count(),
        'watchlist_stocks_count': watchlist_stocks.count(),
        'show_upcoming_dividends': show_upcoming_dividends,
    }
    
    return render(request, 'watchlist_news.html', context)


@login_required
def all_news(request):
    """Display all news prioritizing upcoming dividend stocks, then portfolio and watchlist"""
    # Filter options - determine which stocks to include
    filter_type = request.GET.get('filter', 'all')  # all, portfolio, watchlist, upcoming
    
    # Optimized: Get stock IDs directly instead of full querysets
    cutoff_date = timezone.now() - timedelta(days=7)
    today = timezone.now().date()
    thirty_days_later = today + timedelta(days=30)
    
    # Get stocks with upcoming dividends (next 30 days) - Priority 1
    upcoming_dividend_stock_ids = set(
        Dividend.objects.filter(
            ex_dividend_date__gte=today,
            ex_dividend_date__lte=thirty_days_later
        ).values_list('stock_id', flat=True).distinct()
    )
    
    # Get portfolio and watchlist stock IDs
    portfolio_ids = set(UserPortfolio.objects.filter(user=request.user).values_list('stock_id', flat=True).distinct())
    watchlist_ids = set(Watchlist.objects.filter(user=request.user).values_list('stock_id', flat=True).distinct())
    
    # Determine which stocks to include based on filter
    if filter_type == 'portfolio':
        stock_ids = list(portfolio_ids)
        include_upcoming = True  # Still show upcoming dividends for portfolio stocks
    elif filter_type == 'watchlist':
        stock_ids = list(watchlist_ids)
        include_upcoming = True  # Still show upcoming dividends for watchlist stocks
    elif filter_type == 'upcoming':
        # Only upcoming dividend stocks
        stock_ids = list(upcoming_dividend_stock_ids)
        include_upcoming = False  # Don't double-count
    else:  # 'all'
        # Combine all: upcoming dividends, portfolio, and watchlist
        stock_ids = list(upcoming_dividend_stock_ids | portfolio_ids | watchlist_ids)
        include_upcoming = False  # Already included in stock_ids
    
    # Get recent news (last 7 days) - optimized query
    if stock_ids:
        news_items = StockNews.objects.filter(
            stock_id__in=stock_ids,
            published_at__gte=cutoff_date
        ).select_related('stock').annotate(
            # Annotate with priority: 1 for upcoming dividends, 2 for portfolio, 3 for watchlist
            is_upcoming_dividend=Case(
                When(stock_id__in=upcoming_dividend_stock_ids, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ),
            is_portfolio=Case(
                When(stock_id__in=portfolio_ids, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ),
            is_watchlist=Case(
                When(stock_id__in=watchlist_ids, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ),
        ).order_by(
            '-is_upcoming_dividend',  # Upcoming dividends first
            '-is_portfolio',          # Then portfolio stocks
            '-is_watchlist',          # Then watchlist stocks
            '-published_at'           # Then by date
        )
    else:
        news_items = StockNews.objects.none()
    
    # Get total count before pagination
    total_articles = news_items.count()
    
    # Get counts for context (optimized)
    portfolio_stocks_count = len(portfolio_ids)
    watchlist_stocks_count = len(watchlist_ids)
    upcoming_dividend_stocks_count = len(upcoming_dividend_stock_ids)
    
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
        'upcoming_dividend_stocks_count': upcoming_dividend_stocks_count,
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
@csrf_exempt
@require_POST
def fetch_news(request):
    """
    API endpoint to trigger news fetching for stocks
    Similar to trigger_daily_scrape - runs asynchronously to avoid timeout
    CSRF exempt - uses secret key authentication instead
    
    Parameters:
    - secret_key: Authentication key (required)
    - user: Username to fetch news for their portfolio/watchlist (optional)
    - all: Fetch for all stocks (optional, boolean)
    - portfolio-only: Fetch only for portfolio stocks (optional, boolean)
    - watchlist-only: Fetch only for watchlist stocks (optional, boolean)
    - stocks: Comma-separated list of stock symbols (optional)
    - max-articles: Max articles per stock (default: 5)
    - max-stocks: Max stocks to process (default: 100)
    """
    import threading
    from django.core.management import call_command
    
    # Simple authentication
    secret_key = request.POST.get('secret_key') or request.headers.get('X-API-Key')
    if not secret_key or secret_key != getattr(settings, 'DIVIDEND_ALERT_SECRET', ''):
        logger.warning(f"Unauthorized attempt to fetch news from {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        # Get parameters
        user = request.POST.get('user', '').strip()
        fetch_all = request.POST.get('all', '').lower() == 'true'
        portfolio_only = request.POST.get('portfolio-only', '').lower() == 'true'
        watchlist_only = request.POST.get('watchlist-only', '').lower() == 'true'
        stock_symbols = request.POST.get('stocks', '').strip()
        max_articles = request.POST.get('max-articles', '5')
        max_stocks = request.POST.get('max-stocks', '100')
        
        # Convert to integers with validation
        try:
            max_articles = int(max_articles)
            if max_articles < 1 or max_articles > 20:
                max_articles = 5
        except (ValueError, TypeError):
            max_articles = 5
        
        try:
            max_stocks = int(max_stocks)
            if max_stocks < 1 or max_stocks > 500:
                max_stocks = 100
        except (ValueError, TypeError):
            max_stocks = 100
        
        # Build command arguments
        cmd_args = []
        cmd_options = {
            'max_articles': max_articles,
            'max_stocks': max_stocks,
        }
        
        if user:
            cmd_options['user'] = user
        elif fetch_all:
            cmd_options['all'] = True
        elif portfolio_only:
            cmd_options['portfolio_only'] = True
        elif watchlist_only:
            cmd_options['watchlist_only'] = True
        elif stock_symbols:
            # If specific stocks provided, fetch for those
            symbols = [s.strip().upper() for s in stock_symbols.split(',') if s.strip()]
            if symbols:
                # Use NewsFetcher directly for specific symbols
                stocks = Stock.objects.filter(symbol__in=symbols)
                if stocks.exists():
                    fetcher = NewsFetcher()
                    total_saved = fetcher.fetch_and_save_news(
                        list(stocks),
                        max_articles_per_stock=max_articles
                    )
                    return JsonResponse({
                        'status': 'success',
                        'message': f'Fetched and saved {total_saved} news articles',
                        'stocks_processed': stocks.count(),
                        'articles_saved': total_saved,
                        'symbols': symbols
                    })
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'No stocks found for the provided symbols'
                    }, status=400)
        
        # Run news fetching in background thread to avoid timeout
        def run_news_fetch():
            try:
                logger.info(f"🚀 Starting background news fetch (max_articles={max_articles}, max_stocks={max_stocks})")
                call_command('fetch_stock_news', **cmd_options)
                logger.info(f"✅ Background news fetch completed")
            except Exception as e:
                logger.error(f"❌ Error in background news fetch: {e}")
        
        # Start background thread
        thread = threading.Thread(target=run_news_fetch, daemon=True)
        thread.start()
        
        # Return immediately to avoid timeout
        response_data = {
            'status': 'accepted',
            'message': 'News fetching started in background',
            'max_articles': max_articles,
            'max_stocks': max_stocks,
            'note': 'News fetching is running asynchronously. Check news pages to see results.'
        }
        
        if user:
            response_data['user'] = user
        elif fetch_all:
            response_data['scope'] = 'all_stocks'
        elif portfolio_only:
            response_data['scope'] = 'portfolio_only'
        elif watchlist_only:
            response_data['scope'] = 'watchlist_only'
        else:
            response_data['scope'] = 'portfolio_and_watchlist'
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error triggering news fetch: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Error: {str(e)}'
        }, status=500)


def big6_banks_dashboard(request):
    """Big 6 Canadian Banks Dividend Comparison Dashboard - Accessible to all users"""
    from django.db.models import Subquery, OuterRef, Q, Avg
    from datetime import timedelta
    from portfolio.models import Stock, StockPrice, Dividend, UserPortfolio, Watchlist
    
    # Big 6 Canadian Banks
    BIG_6_BANKS = {
        'RY': {'name': 'Royal Bank of Canada', 'full_name': 'Royal Bank of Canada'},
        'TD': {'name': 'TD Bank', 'full_name': 'The Toronto-Dominion Bank'},
        'BNS': {'name': 'Bank of Nova Scotia', 'full_name': 'Bank of Nova Scotia'},
        'BMO': {'name': 'Bank of Montreal', 'full_name': 'Bank of Montreal'},
        'CM': {'name': 'CIBC', 'full_name': 'Canadian Imperial Bank of Commerce'},
        'NA': {'name': 'National Bank', 'full_name': 'National Bank of Canada'},
    }
    
    # Get stocks with annotations
    bank_symbols = list(BIG_6_BANKS.keys())
    stocks = Stock.objects.filter(symbol__in=bank_symbols).annotate(
        latest_price_value=Subquery(
            StockPrice.objects.filter(stock=OuterRef('pk'))
            .order_by('-price_date').values('last_price')[:1]
        ),
        latest_price_date=Subquery(
            StockPrice.objects.filter(stock=OuterRef('pk'))
            .order_by('-price_date').values('price_date')[:1]
        ),
        latest_dividend_amount=Subquery(
            Dividend.objects.filter(stock=OuterRef('pk'))
            .order_by('-ex_dividend_date').values('amount')[:1]
        ),
        latest_dividend_yield=Subquery(
            Dividend.objects.filter(stock=OuterRef('pk'))
            .order_by('-ex_dividend_date').values('yield_percent')[:1]
        ),
        latest_dividend_frequency=Subquery(
            Dividend.objects.filter(stock=OuterRef('pk'))
            .order_by('-ex_dividend_date').values('frequency')[:1]
        ),
        latest_dividend_date=Subquery(
            Dividend.objects.filter(stock=OuterRef('pk'))
            .order_by('-ex_dividend_date').values('ex_dividend_date')[:1]
        ),
        next_dividend_date=Subquery(
            Dividend.objects.filter(
                stock=OuterRef('pk'),
                ex_dividend_date__gte=timezone.now().date()
            ).order_by('ex_dividend_date').values('ex_dividend_date')[:1]
        ),
    )
    
    # Calculate additional metrics for each bank
    banks_data = []
    today = timezone.now().date()
    one_year_ago = today - timedelta(days=365)
    three_years_ago = today - timedelta(days=1095)
    
    for stock in stocks:
        if stock.symbol not in BIG_6_BANKS:
            continue
            
        bank_info = BIG_6_BANKS[stock.symbol]
        
        # Get dividend history for growth calculation
        dividends = Dividend.objects.filter(stock=stock).order_by('-ex_dividend_date')
        recent_dividends = dividends[:4]  # Last 4 dividends
        
        # Calculate dividend growth (1-year and 3-year)
        dividend_growth_1y = None
        dividend_growth_3y = None
        
        if dividends.count() >= 2:
            latest = dividends[0]
            one_year_ago_dividend = dividends.filter(ex_dividend_date__lte=one_year_ago).first()
            three_years_ago_dividend = dividends.filter(ex_dividend_date__lte=three_years_ago).first()
            
            if one_year_ago_dividend:
                growth = ((float(latest.amount) - float(one_year_ago_dividend.amount)) / 
                         float(one_year_ago_dividend.amount)) * 100
                dividend_growth_1y = round(growth, 2)
            
            if three_years_ago_dividend:
                growth = ((float(latest.amount) - float(three_years_ago_dividend.amount)) / 
                         float(three_years_ago_dividend.amount)) * 100
                dividend_growth_3y = round(growth, 2)
        
        # Calculate consecutive increases (dividend growth streak)
        growth_streak = 0
        sorted_dividends = list(dividends[:10])  # Check last 10 dividends
        for i in range(len(sorted_dividends) - 1):
            if float(sorted_dividends[i].amount) > float(sorted_dividends[i + 1].amount):
                growth_streak += 1
            else:
                break
        
        # Calculate annual dividend
        annual_dividend = 0
        if stock.latest_dividend_amount and stock.latest_dividend_frequency:
            frequency_multiplier = {
                'Monthly': 12,
                'Quarterly': 4,
                'Semi-Annual': 2,
                'Annual': 1,
            }.get(stock.latest_dividend_frequency, 4)  # Default to quarterly
            annual_dividend = float(stock.latest_dividend_amount) * frequency_multiplier
        
        # Check if user owns this stock
        user_owns = False
        user_shares = 0
        if request.user.is_authenticated:
            portfolio_item = UserPortfolio.objects.filter(
                user=request.user, 
                stock=stock
            ).first()
            if portfolio_item:
                user_owns = True
                user_shares = portfolio_item.shares_owned
        
        # Check if in watchlist
        in_watchlist = False
        if request.user.is_authenticated:
            in_watchlist = Watchlist.objects.filter(user=request.user, stock=stock).exists()
        
        banks_data.append({
            'stock': stock,
            'name': bank_info['name'],
            'full_name': bank_info['full_name'],
            'symbol': stock.symbol,
            'price': stock.latest_price_value,
            'price_date': stock.latest_price_date,
            'dividend_amount': stock.latest_dividend_amount,
            'dividend_yield': stock.latest_dividend_yield,
            'dividend_frequency': stock.latest_dividend_frequency or 'Quarterly',
            'annual_dividend': annual_dividend,
            'dividend_growth_1y': dividend_growth_1y,
            'dividend_growth_3y': dividend_growth_3y,
            'growth_streak': growth_streak,
            'next_dividend_date': stock.next_dividend_date,
            'user_owns': user_owns,
            'user_shares': user_shares,
            'in_watchlist': in_watchlist,
        })
    
    # Sort by yield (highest first) or by symbol
    sort_by = request.GET.get('sort', 'yield')
    if sort_by == 'yield':
        banks_data.sort(key=lambda x: x['dividend_yield'] or 0, reverse=True)
    elif sort_by == 'growth':
        banks_data.sort(key=lambda x: x['dividend_growth_1y'] or 0, reverse=True)
    elif sort_by == 'streak':
        banks_data.sort(key=lambda x: x['growth_streak'], reverse=True)
    elif sort_by == 'symbol':
        banks_data.sort(key=lambda x: x['symbol'])
    
    # Calculate averages
    avg_yield = sum(b['dividend_yield'] or 0 for b in banks_data) / len(banks_data) if banks_data else 0
    avg_growth_1y = sum(b['dividend_growth_1y'] or 0 for b in banks_data) / len([b for b in banks_data if b['dividend_growth_1y']]) if any(b['dividend_growth_1y'] for b in banks_data) else 0
    avg_growth_streak = sum(b['growth_streak'] for b in banks_data) / len(banks_data) if banks_data else 0
    
    context = {
        'banks_data': banks_data,
        'avg_yield': round(avg_yield, 2),
        'avg_growth_1y': round(avg_growth_1y, 2),
        'avg_growth_streak': round(avg_growth_streak, 1),
        'sort_by': sort_by,
    }
    
    return render(request, 'big6_banks_dashboard.html', context)


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


@csrf_protect
def contact_us(request):
    """Contact Us page with email sending and security features"""
    from .forms import ContactForm
    from portfolio.utils.email_service import send_email
    from django.conf import settings
    from datetime import datetime, timedelta
    
    # Rate limiting: max 3 submissions per hour per IP
    if request.method == 'POST':
        session_key = f'contact_submissions_{request.META.get("REMOTE_ADDR", "unknown")}'
        submissions = request.session.get(session_key, [])
        
        # Remove submissions older than 1 hour
        now = datetime.now()
        submissions = [s for s in submissions if (now - datetime.fromisoformat(s)).total_seconds() < 3600]
        
        if len(submissions) >= 3:
            messages.error(request, 'Too many submissions. Please wait before sending another message.')
            form = ContactForm()
            return render(request, 'contact.html', {'form': form})
        
        form = ContactForm(request.POST)
        if form.is_valid():
            # Check honeypot field
            if form.cleaned_data.get('website'):
                logger.warning(f"Spam detected from {request.META.get('REMOTE_ADDR')}")
                messages.error(request, 'Invalid submission.')
                form = ContactForm()
                return render(request, 'contact.html', {'form': form})
            
            name = form.cleaned_data['name']
            email = form.cleaned_data['email']
            subject = form.cleaned_data['subject']
            message = form.cleaned_data['message']
            
            # Get recipient email (admin email or default from email)
            recipient_email = getattr(settings, 'CONTACT_EMAIL', None) or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@dividend.forum')
            
            # Prepare email content
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #2563eb;">New Contact Form Submission</h2>
                    <div style="background-color: #f3f4f6; padding: 15px; border-radius: 5px; margin: 20px 0;">
                        <p><strong>Name:</strong> {name}</p>
                        <p><strong>Email:</strong> {email}</p>
                        <p><strong>Subject:</strong> {subject}</p>
                        <p><strong>Submitted:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p><strong>IP Address:</strong> {request.META.get('REMOTE_ADDR', 'Unknown')}</p>
                    </div>
                    <div style="background-color: #ffffff; padding: 15px; border-left: 4px solid #2563eb; margin: 20px 0;">
                        <h3 style="margin-top: 0;">Message:</h3>
                        <p style="white-space: pre-wrap;">{message}</p>
                    </div>
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                    <p style="color: #6b7280; font-size: 12px;">
                        This email was sent from the Contact Us form on dividend.forum
                    </p>
                </div>
            </body>
            </html>
            """
            
            text_content = f"""
New Contact Form Submission

Name: {name}
Email: {email}
Subject: {subject}
Submitted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
IP Address: {request.META.get('REMOTE_ADDR', 'Unknown')}

Message:
{message}

---
This email was sent from the Contact Us form on dividend.forum
            """
            
            # Send email
            email_subject = f"Contact Form: {subject}"
            success = send_email(
                to_email=recipient_email,
                subject=email_subject,
                html_content=html_content,
                text_content=text_content
            )
            
            if success:
                # Record submission for rate limiting
                submissions.append(now.isoformat())
                request.session[session_key] = submissions
                request.session.modified = True
                
                messages.success(request, 'Thank you for contacting us! We will get back to you soon.')
                logger.info(f"Contact form submitted successfully from {email} (IP: {request.META.get('REMOTE_ADDR')})")
                form = ContactForm()  # Reset form
            else:
                messages.error(request, 'Sorry, there was an error sending your message. Please try again later.')
                logger.error(f"Failed to send contact form email from {email}")
    else:
        form = ContactForm()
    
    return render(request, 'contact.html', {'form': form})


def donations(request):
    """Donations page with payment widgets"""
    return render(request, 'donations.html')


def privacy_policy(request):
    """Privacy Policy page"""
    return render(request, 'privacy_policy.html')


def terms_of_service(request):
    """Terms of Service page"""
    return render(request, 'terms_of_service.html')


# ==================== SOCIAL FEATURES ====================

@login_required
def user_profile(request, username):
    """View user profile"""
    from django.contrib.auth.models import User
    from portfolio.models import UserProfile, Post, Follow
    
    profile_user = get_object_or_404(User, username=username)
    
    # Get or create profile
    profile, created = UserProfile.objects.get_or_create(user=profile_user)
    
    # Check if current user is following this user
    is_following = False
    if request.user.is_authenticated and request.user != profile_user:
        is_following = Follow.objects.filter(follower=request.user, following=profile_user).exists()
    
    # Get user's posts
    posts = Post.objects.filter(user=profile_user).select_related('stock', 'user').prefetch_related('post_likes')[:10]
    
    # Get followers and following counts
    followers_count = profile_user.followers.count()
    following_count = profile_user.following.count()
    posts_count = posts.count()
    
    context = {
        'profile_user': profile_user,
        'profile': profile,
        'posts': posts,
        'is_following': is_following,
        'followers_count': followers_count,
        'following_count': following_count,
        'posts_count': posts_count,
        'is_own_profile': request.user == profile_user,
    }
    return render(request, 'social/user_profile.html', context)


@login_required
def edit_profile(request):
    """Edit user profile"""
    from portfolio.models import UserProfile
    
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        profile.bio = request.POST.get('bio', '')
        profile.avatar = request.POST.get('avatar', '')
        profile.location = request.POST.get('location', '')
        profile.website = request.POST.get('website', '')
        profile.twitter_handle = request.POST.get('twitter_handle', '')
        profile.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('user_profile', username=request.user.username)
    
    context = {'profile': profile}
    return render(request, 'social/edit_profile.html', context)


@login_required
@require_POST
def follow_user(request, username):
    """Follow or unfollow a user"""
    from django.contrib.auth.models import User
    from portfolio.models import Follow
    
    user_to_follow = get_object_or_404(User, username=username)
    
    if user_to_follow == request.user:
        return JsonResponse({'status': 'error', 'message': 'Cannot follow yourself'}, status=400)
    
    follow, created = Follow.objects.get_or_create(follower=request.user, following=user_to_follow)
    
    if created:
        return JsonResponse({'status': 'success', 'message': f'Now following {username}', 'action': 'follow'})
    else:
        follow.delete()
        return JsonResponse({'status': 'success', 'message': f'Unfollowed {username}', 'action': 'unfollow'})


@login_required
def posts_feed(request):
    """View posts feed - all posts or from followed users"""
    from portfolio.models import Post, PostLike
    
    feed_type = request.GET.get('feed', 'all')  # all, following, stock
    
    if feed_type == 'following':
        # Get posts from users being followed
        following_ids = request.user.following.values_list('following_id', flat=True)
        posts = Post.objects.filter(user_id__in=following_ids).select_related('user', 'stock').prefetch_related('post_likes', 'comments')
    elif feed_type == 'stock':
        stock_symbol = request.GET.get('symbol')
        if stock_symbol:
            from portfolio.models import Stock
            stock = get_object_or_404(Stock, symbol=stock_symbol)
            posts = Post.objects.filter(stock=stock).select_related('user', 'stock').prefetch_related('post_likes', 'comments')
        else:
            posts = Post.objects.none()
    else:
        # All posts
        posts = Post.objects.all().select_related('user', 'stock').prefetch_related('post_likes', 'comments')
    
    # Get liked posts by current user
    liked_post_ids = set()
    if request.user.is_authenticated:
        liked_post_ids = set(PostLike.objects.filter(user=request.user).values_list('post_id', flat=True))
    
    # Pagination
    paginator = Paginator(posts, 10)
    page = request.GET.get('page')
    try:
        posts_page = paginator.page(page)
    except PageNotAnInteger:
        posts_page = paginator.page(1)
    except EmptyPage:
        posts_page = paginator.page(paginator.num_pages)
    
    # Mark which posts are liked
    for post in posts_page:
        post.is_liked = post.id in liked_post_ids
        post.increment_views()
    
    context = {
        'posts': posts_page,
        'feed_type': feed_type,
    }
    return render(request, 'social/posts_feed.html', context)


@login_required
def create_post(request):
    """Create a new post"""
    from portfolio.models import Post, Stock
    
    if request.method == 'POST':
        post_type = request.POST.get('post_type', 'insight')
        title = request.POST.get('title', '')
        content = request.POST.get('content', '')
        stock_symbol = request.POST.get('stock_symbol', '')
        
        if not content:
            messages.error(request, 'Post content is required.')
            return redirect('posts_feed')
        
        stock = None
        if stock_symbol:
            try:
                stock = Stock.objects.get(symbol=stock_symbol)
            except Stock.DoesNotExist:
                pass
        
        post = Post.objects.create(
            user=request.user,
            post_type=post_type,
            title=title,
            content=content,
            stock=stock
        )
        
        messages.success(request, 'Post created successfully!')
        return redirect('posts_feed')
    
    # Get stocks for dropdown
    stocks = Stock.objects.all().order_by('symbol')[:100]
    
    context = {'stocks': stocks}
    return render(request, 'social/create_post.html', context)


@login_required
def post_detail(request, post_id):
    """View post detail with comments"""
    from portfolio.models import Post, PostLike, Comment, CommentLike
    
    post = get_object_or_404(Post.objects.select_related('user', 'stock').prefetch_related('comments__user'), id=post_id)
    
    # Check if liked
    is_liked = False
    if request.user.is_authenticated:
        is_liked = PostLike.objects.filter(post=post, user=request.user).exists()
    
    # Get comments
    comments = post.comments.all().select_related('user')
    
    # Get liked comment IDs
    liked_comment_ids = set()
    if request.user.is_authenticated:
        liked_comment_ids = set(CommentLike.objects.filter(user=request.user, comment__in=comments).values_list('comment_id', flat=True))
    
    for comment in comments:
        comment.is_liked = comment.id in liked_comment_ids
    
    # Increment view count
    post.increment_views()
    
    context = {
        'post': post,
        'comments': comments,
        'is_liked': is_liked,
    }
    return render(request, 'social/post_detail.html', context)


@login_required
@require_POST
def like_post(request, post_id):
    """Like or unlike a post"""
    from portfolio.models import Post, PostLike
    
    post = get_object_or_404(Post, id=post_id)
    
    like, created = PostLike.objects.get_or_create(post=post, user=request.user)
    
    if created:
        return JsonResponse({'status': 'success', 'action': 'liked', 'likes_count': post.likes_count})
    else:
        like.delete()
        return JsonResponse({'status': 'success', 'action': 'unliked', 'likes_count': post.likes_count})


@login_required
@require_POST
def add_comment(request, post_id):
    """Add a comment to a post"""
    from portfolio.models import Post, Comment
    
    post = get_object_or_404(Post, id=post_id)
    content = request.POST.get('content', '').strip()
    
    if not content:
        return JsonResponse({'status': 'error', 'message': 'Comment cannot be empty'}, status=400)
    
    comment = Comment.objects.create(post=post, user=request.user, content=content)
    post.comments_count = post.comments.count()
    post.save(update_fields=['comments_count'])
    
    return JsonResponse({
        'status': 'success',
        'comment': {
            'id': comment.id,
            'content': comment.content,
            'user': comment.user.username,
            'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }
    })


@login_required
@require_POST
def like_comment(request, comment_id):
    """Like or unlike a comment"""
    from portfolio.models import Comment, CommentLike
    
    comment = get_object_or_404(Comment, id=comment_id)
    
    like, created = CommentLike.objects.get_or_create(comment=comment, user=request.user)
    
    if created:
        return JsonResponse({'status': 'success', 'action': 'liked', 'likes_count': comment.likes_count})
    else:
        like.delete()
        return JsonResponse({'status': 'success', 'action': 'unliked', 'likes_count': comment.likes_count})


@login_required
def followers_list(request, username):
    """View list of followers"""
    from django.contrib.auth.models import User
    from portfolio.models import Follow
    
    user = get_object_or_404(User, username=username)
    followers = Follow.objects.filter(following=user).select_related('follower')[:50]
    
    context = {
        'profile_user': user,
        'followers': followers,
        'is_own_profile': request.user == user,
    }
    return render(request, 'social/followers_list.html', context)


@login_required
def following_list(request, username):
    """View list of users being followed"""
    from django.contrib.auth.models import User
    from portfolio.models import Follow
    
    user = get_object_or_404(User, username=username)
    following = Follow.objects.filter(follower=user).select_related('following')[:50]
    
    context = {
        'profile_user': user,
        'following': following,
        'is_own_profile': request.user == user,
    }
    return render(request, 'social/following_list.html', context)


# Stock Notes & Journal Views
@login_required
def stock_notes(request, symbol=None):
    """View all notes for a user, optionally filtered by stock"""
    try:
        search_query = request.GET.get('search', '')
        note_type_filter = request.GET.get('type', '')
        tag_filter = request.GET.get('tag', '')
        
        notes = StockNote.objects.filter(user=request.user).select_related('stock').order_by('-created_at')
        
        # Filter by stock if symbol provided
        stock = None
        if symbol:
            stock = get_object_or_404(Stock, symbol=symbol.upper())
            notes = notes.filter(stock=stock)
        
        # Filter by search query
        if search_query:
            notes = notes.filter(
                Q(title__icontains=search_query) |
                Q(content__icontains=search_query) |
                Q(tags__icontains=search_query) |
                Q(stock__symbol__icontains=search_query) |
                Q(stock__company_name__icontains=search_query)
            )
        
        # Filter by note type
        if note_type_filter:
            notes = notes.filter(note_type=note_type_filter)
        
        # Filter by tag
        if tag_filter:
            notes = notes.filter(tags__icontains=tag_filter)
        
        # Get unique tags and note types for filters (before pagination)
        all_tags = set()
        for note in notes[:100]:  # Limit to first 100 for performance
            all_tags.update(note.get_tags_list())
        
        # Pagination
        paginator = Paginator(notes, 20)
        page = request.GET.get('page', 1)
        try:
            notes_page = paginator.page(page)
        except (EmptyPage, PageNotAnInteger):
            notes_page = paginator.page(1)
        
        context = {
            'notes': notes_page,
            'search_query': search_query,
            'note_type_filter': note_type_filter,
            'tag_filter': tag_filter,
            'all_tags': sorted(all_tags),
            'note_types': StockNote.NOTE_TYPE_CHOICES,
            'stock': stock,
        }
        
        return render(request, 'notes/notes_list.html', context)
    except (ProgrammingError, OperationalError, DatabaseError, Exception) as e:
        # Table might not exist yet if migration hasn't been run
        logger.warning(f"StockNote table not found: {e}")
        messages.error(request, 'Notes feature is not available yet. Please run migrations: python manage.py migrate')
        return redirect('dashboard')


@login_required
def create_stock_note(request, symbol):
    """Create a new note for a stock"""
    try:
        stock = get_object_or_404(Stock, symbol=symbol.upper())
    except (ProgrammingError, OperationalError, DatabaseError, Exception) as e:
        logger.warning(f"StockNote table not found: {e}")
        messages.error(request, 'Notes feature is not available yet. Please run migrations: python manage.py migrate')
        return redirect('stock_detail', symbol=symbol)
    
    if request.method == 'POST':
        note_type = request.POST.get('note_type', 'note')
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()
        tags = request.POST.get('tags', '').strip()
        is_private = request.POST.get('is_private', 'on') == 'on'
        
        if not content:
            messages.error(request, 'Note content is required.')
            return redirect('create_stock_note', symbol=symbol)
        
        try:
            note = StockNote.objects.create(
                user=request.user,
                stock=stock,
                note_type=note_type,
                title=title,
                content=content,
                tags=tags,
                is_private=is_private
            )
            
            messages.success(request, 'Note created successfully!')
            return redirect('stock_detail', symbol=symbol)
        except (ProgrammingError, OperationalError, DatabaseError, Exception) as e:
            logger.warning(f"StockNote table not found: {e}")
            messages.error(request, 'Notes feature is not available yet. Please run migrations: python manage.py migrate')
            return redirect('stock_detail', symbol=symbol)
    
    context = {
        'stock': stock,
        'note_types': StockNote.NOTE_TYPE_CHOICES,
    }
    return render(request, 'notes/create_note.html', context)


@login_required
def edit_stock_note(request, note_id):
    """Edit an existing note"""
    try:
        note = get_object_or_404(StockNote, id=note_id, user=request.user)
        
        if request.method == 'POST':
            note.note_type = request.POST.get('note_type', note.note_type)
            note.title = request.POST.get('title', '').strip()
            note.content = request.POST.get('content', '').strip()
            note.tags = request.POST.get('tags', '').strip()
            note.is_private = request.POST.get('is_private', 'on') == 'on'
            
            if not note.content:
                messages.error(request, 'Note content is required.')
                return redirect('edit_stock_note', note_id=note_id)
            
            note.save()
            messages.success(request, 'Note updated successfully!')
            return redirect('stock_detail', symbol=note.stock.symbol)
        
        context = {
            'note': note,
            'note_types': StockNote.NOTE_TYPE_CHOICES,
        }
        return render(request, 'notes/edit_note.html', context)
    except (ProgrammingError, OperationalError, DatabaseError, Exception) as e:
        logger.warning(f"StockNote table not found: {e}")
        messages.error(request, 'Notes feature is not available yet. Please run migrations: python manage.py migrate')
        return redirect('dashboard')


@login_required
@require_POST
def delete_stock_note(request, note_id):
    """Delete a note"""
    try:
        note = get_object_or_404(StockNote, id=note_id, user=request.user)
        stock_symbol = note.stock.symbol
        note.delete()
        messages.success(request, 'Note deleted successfully!')
        return redirect('stock_detail', symbol=stock_symbol)
    except (ProgrammingError, OperationalError, DatabaseError, Exception) as e:
        logger.warning(f"StockNote table not found: {e}")
        messages.error(request, 'Notes feature is not available yet. Please run migrations: python manage.py migrate')
        return redirect('dashboard')


@login_required
def export_notes(request):
    """Export all user notes to CSV"""
    try:
        notes = StockNote.objects.filter(user=request.user).select_related('stock').order_by('-created_at')
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="stock_notes_{request.user.username}_{timezone.now().date()}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Date', 'Stock Symbol', 'Company Name', 'Note Type', 'Title', 'Content', 'Tags', 'Private'])
        
        for note in notes:
            writer.writerow([
                note.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                note.stock.symbol,
                note.stock.company_name,
                note.get_note_type_display(),
                note.title,
                note.content,
                note.tags,
                'Yes' if note.is_private else 'No'
            ])
        
        return response
    except (ProgrammingError, OperationalError, DatabaseError, Exception) as e:
        logger.warning(f"StockNote table not found: {e}")
        messages.error(request, 'Notes feature is not available yet. Please run migrations: python manage.py migrate')
        return redirect('dashboard')

@login_required
def website_analytics(request):
    """View website analytics - IP addresses, user details, and metrics"""
    # Only allow staff/superusers to view analytics
    if not request.user.is_staff:
        messages.error(request, 'You do not have permission to view analytics.')
        return redirect('dashboard')
    
    import re
    from urllib.parse import urlparse
    from datetime import timedelta
    from django.db.models import Count, Q, Avg
    from portfolio.models import WebsiteMetric, UserSession
    
    # Get date range from query params (default: last 7 days)
    days = int(request.GET.get('days', 7))
    start_date = timezone.now() - timedelta(days=days)
    
    # Get metrics
    metrics = WebsiteMetric.objects.filter(timestamp__gte=start_date).select_related('user')
    
    # Statistics
    total_visits = metrics.count()
    unique_ips = metrics.exclude(ip_address=None).values('ip_address').distinct().count()
    unique_users = metrics.exclude(user=None).values('user').distinct().count()
    unique_sessions = metrics.exclude(session_key='').values('session_key').distinct().count()
    
    # Device breakdown
    mobile_visits = metrics.filter(is_mobile=True).count()
    bot_visits = metrics.filter(is_bot=True).count()
    authenticated_visits = metrics.filter(is_authenticated=True).count()
    
    # Top IPs with additional info
    top_ips_raw = list(metrics.exclude(ip_address=None).values('ip_address', 'country', 'city', 'region', 'timezone', 'user_agent').annotate(
        visit_count=Count('id'),
        user_count=Count('user', distinct=True)
    ).order_by('-visit_count')[:20])
    
    # Process IPs with browser/OS info
    top_ips = []
    for ip_data in top_ips_raw:
        ip_info = dict(ip_data)
        # Extract browser from user_agent
        user_agent = ip_data.get('user_agent', '')
        browser = 'Unknown'
        os_info = 'Unknown'
        
        if user_agent:
            # Browser detection
            if 'Chrome' in user_agent and 'Edg' not in user_agent:
                browser = 'Chrome'
            elif 'Firefox' in user_agent:
                browser = 'Firefox'
            elif 'Safari' in user_agent and 'Chrome' not in user_agent:
                browser = 'Safari'
            elif 'Edg' in user_agent:
                browser = 'Edge'
            elif 'Opera' in user_agent or 'OPR' in user_agent:
                browser = 'Opera'
            
            # OS detection
            if 'Windows' in user_agent:
                os_info = 'Windows'
            elif 'Mac' in user_agent or 'Macintosh' in user_agent:
                os_info = 'macOS'
            elif 'Linux' in user_agent:
                os_info = 'Linux'
            elif 'Android' in user_agent:
                os_info = 'Android'
            elif 'iOS' in user_agent or 'iPhone' in user_agent or 'iPad' in user_agent:
                os_info = 'iOS'
        
        ip_info['browser'] = browser
        ip_info['os'] = os_info
        top_ips.append(ip_info)
    
    # Top users
    top_users = metrics.exclude(user=None).values('user__username', 'user__email', 'user__id').annotate(
        visit_count=Count('id'),
        unique_ips=Count('ip_address', distinct=True)
    ).order_by('-visit_count')[:20]
    
    # Top pages
    top_pages = metrics.values('path').annotate(
        view_count=Count('id'),
        unique_visitors=Count('ip_address', distinct=True)
    ).order_by('-view_count')[:20]
    
    # Traffic sources (referrers)
    referrer_stats = []
    referrers = metrics.exclude(referrer='').values('referrer').annotate(
        visit_count=Count('id')
    ).order_by('-visit_count')[:20]
    
    for ref in referrers:
        ref_url = ref['referrer']
        try:
            parsed = urlparse(ref_url)
            domain = parsed.netloc.replace('www.', '')
            if domain:
                referrer_stats.append({
                    'domain': domain,
                    'full_url': ref_url[:100],
                    'visit_count': ref['visit_count']
                })
        except:
            referrer_stats.append({
                'domain': ref_url[:50],
                'full_url': ref_url[:100],
                'visit_count': ref['visit_count']
            })
    
    # Browser breakdown
    browser_stats = {}
    for metric in metrics.exclude(user_agent=''):
        user_agent = metric.user_agent
        browser = 'Unknown'
        if 'Chrome' in user_agent and 'Edg' not in user_agent:
            browser = 'Chrome'
        elif 'Firefox' in user_agent:
            browser = 'Firefox'
        elif 'Safari' in user_agent and 'Chrome' not in user_agent:
            browser = 'Safari'
        elif 'Edg' in user_agent:
            browser = 'Edge'
        elif 'Opera' in user_agent or 'OPR' in user_agent:
            browser = 'Opera'
        
        browser_stats[browser] = browser_stats.get(browser, 0) + 1
    
    browser_stats = sorted(browser_stats.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # OS breakdown
    os_stats = {}
    for metric in metrics.exclude(user_agent=''):
        user_agent = metric.user_agent
        os_info = 'Unknown'
        if 'Windows' in user_agent:
            os_info = 'Windows'
        elif 'Mac' in user_agent or 'Macintosh' in user_agent:
            os_info = 'macOS'
        elif 'Linux' in user_agent:
            os_info = 'Linux'
        elif 'Android' in user_agent:
            os_info = 'Android'
        elif 'iOS' in user_agent or 'iPhone' in user_agent or 'iPad' in user_agent:
            os_info = 'iOS'
        
        os_stats[os_info] = os_stats.get(os_info, 0) + 1
    
    os_stats = sorted(os_stats.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Hourly activity pattern
    hourly_stats = metrics.extra(
        select={'hour': "EXTRACT(hour FROM timestamp)"}
    ).values('hour').annotate(
        visit_count=Count('id')
    ).order_by('hour')
    
    # Recent activity
    recent_activity = metrics.select_related('user').order_by('-timestamp')[:50]
    
    # Average response time
    avg_response_time = metrics.exclude(response_time_ms=None).aggregate(
        avg=Avg('response_time_ms')
    )['avg'] or 0
    
    # Country breakdown (if available)
    country_stats = metrics.exclude(country='').values('country').annotate(
        visit_count=Count('id')
    ).order_by('-visit_count')[:20]
    
    # Direct vs Referral traffic
    direct_traffic = metrics.filter(referrer='').count()
    referral_traffic = metrics.exclude(referrer='').count()
    
    context = {
        'total_visits': total_visits,
        'unique_ips': unique_ips,
        'unique_users': unique_users,
        'unique_sessions': unique_sessions,
        'mobile_visits': mobile_visits,
        'bot_visits': bot_visits,
        'authenticated_visits': authenticated_visits,
        'top_ips': top_ips,
        'top_users': top_users,
        'top_pages': top_pages,
        'recent_activity': recent_activity,
        'avg_response_time': round(avg_response_time, 2),
        'country_stats': country_stats,
        'browser_stats': browser_stats,
        'os_stats': os_stats,
        'referrer_stats': referrer_stats,
        'hourly_stats': hourly_stats,
        'direct_traffic': direct_traffic,
        'referral_traffic': referral_traffic,
        'days': days,
        'start_date': start_date,
    }
    
    return render(request, 'website_analytics.html', context)
