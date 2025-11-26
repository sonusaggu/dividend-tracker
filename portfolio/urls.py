from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # SEO and static files
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('favicon.ico', views.favicon_view, name='favicon'),
    
    # Redirect old Django auth URLs to custom URLs
    path('accounts/login/', views.login_view, name='django_login_redirect'),
    
    path('', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    
    # Password reset URLs
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(
             template_name='password_reset.html',
             email_template_name='password_reset_email.html',
             subject_template_name='password_reset_subject.txt',
             success_url='/password-reset/done/',
             extra_email_context={'site_name': 'StockFolio'},
             from_email=None  # Will use DEFAULT_FROM_EMAIL from settings
         ), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(
             template_name='password_reset_done.html'
         ), 
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='password_reset_confirm.html',
             success_url='/password-reset-complete/'
         ), 
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(
             template_name='password_reset_complete.html'
         ), 
         name='password_reset_complete'),
    
    # Email verification URLs
    path('verify-email/<str:token>/', views.verify_email, name='verify_email'),
    path('verify-email-sent/', views.verify_email_sent, name='verify_email_sent'),
    path('resend-verification/', views.resend_verification_email, name='resend_verification'),
    
    path('dashboard/', views.dashboard, name='dashboard'),
    path('stocks/', views.all_stocks_view, name='all_stocks'),
    path('stocks/<str:symbol>/', views.stock_detail, name='stock_detail'),
    path('stocks/<str:symbol>/dividend-history/', views.dividend_history, name='dividend_history'),
    path('dividend-calendar/', views.dividend_calendar, name='dividend_calendar'),
    path('watchlist/toggle/<int:stock_id>/', views.toggle_watchlist, name='toggle_watchlist'),
    path('portfolio/add/<str:symbol>/', views.add_to_portfolio, name='add_to_portfolio'),
    path('dividend-alerts/<int:stock_id>/', views.manage_dividend_alerts, name='manage_dividend_alerts'),
    path('watchlist/', views.watchlist_view, name='watchlist'),
    path('portfolio/', views.portfolio_view, name='portfolio'),
    path('portfolio/export/', views.export_portfolio, name='export_portfolio'),
    path('check-watchlist/<int:stock_id>/', views.check_watchlist_status, name='check_watchlist_status'),
    path('stock/<str:symbol>/alerts/', views.manage_dividend_alerts, name='manage_dividend_alerts'),
    path('stock/<str:symbol>/alerts/toggle/', views.toggle_dividend_alert, name='toggle_dividend_alert'),
    path('my-alerts/', views.my_alerts, name='my_alerts'),
    path('trigger-dividend-alerts/', views.trigger_dividend_alerts, name='trigger_dividend_alerts'),
    path('trigger-daily-scrape/', views.trigger_daily_scrape, name='trigger_daily_scrape'),
    path('trigger-newsletter/', views.trigger_newsletter, name='trigger_newsletter'),
    path('scrape-status/', views.scrape_status, name='scrape_status'),
    path('delete-alert/<int:alert_id>/', views.delete_dividend_alert, name='delete_dividend_alert'),
    path('newsletter/', views.newsletter_subscription, name='newsletter_subscription'),
    # News aggregation routes
    path('news/', views.all_news, name='all_news'),
    path('news/portfolio/', views.portfolio_news, name='portfolio_news'),
    path('news/watchlist/', views.watchlist_news, name='watchlist_news'),
    path('stocks/<str:symbol>/news/', views.stock_news, name='stock_news'),
    path('fetch-news/', views.fetch_news, name='fetch_news'),
    # Canadian tools
    path('tools/', views.canadian_tools, name='canadian_tools'),
    # Contact Us
    path('contact/', views.contact_us, name='contact_us'),
    # Donations
    path('donate/', views.donations, name='donations'),
    # Legal Pages
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms-of-service/', views.terms_of_service, name='terms_of_service'),
    # Search improvements
    path('api/stock-search/', views.stock_search_autocomplete, name='stock_search_autocomplete'),
    # Affiliate and Sponsored Content
    path('affiliate/<int:affiliate_id>/', views.track_affiliate_click, name='track_affiliate_click'),
    path('sponsored/<int:content_id>/', views.track_sponsored_click, name='track_sponsored_click'),

]