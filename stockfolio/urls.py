from django.contrib import admin
from django.urls import path, include

# Import custom error handlers
from portfolio import error_handlers

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('portfolio.urls')),  # This will use your home view
]

# Set custom error handlers
handler500 = error_handlers.handler500