from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('stocks/', views.all_stocks_view, name='all_stocks'),
    path('stocks/<str:symbol>/', views.stock_detail, name='stock_detail'),
    path('watchlist/toggle/<int:stock_id>/', views.toggle_watchlist, name='toggle_watchlist'),
    path('portfolio/add/<str:symbol>/', views.add_to_portfolio, name='add_to_portfolio'),
    path('dividend-alerts/<int:stock_id>/', views.manage_dividend_alerts, name='manage_dividend_alerts'),
    path('watchlist/', views.watchlist_view, name='watchlist'),
    path('portfolio/', views.portfolio_view, name='portfolio'),
    path('check-watchlist/<int:stock_id>/', views.check_watchlist_status, name='check_watchlist_status'),
    path('set-alert/<str:symbol>/', views.set_alert, name='set_alert'),
]