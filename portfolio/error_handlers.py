"""
Custom error handlers for Django
"""
from django.http import HttpResponseServerError
from django.template.loader import render_to_string
from django.db import OperationalError, DatabaseError, InterfaceError
import logging

logger = logging.getLogger(__name__)


def handler500(request, *args, **kwargs):
    """Custom 500 error handler that shows user-friendly database error page"""
    exception = kwargs.get('exception') or (args[0] if args else None)
    
    # Check if this is a database connection error
    if exception and isinstance(exception, (OperationalError, DatabaseError, InterfaceError)):
        error_str = str(exception).lower()
        if any(keyword in error_str for keyword in [
            'connection refused', 'connection', 'server', 'tcp/ip',
            'could not connect', 'unable to connect', 'connection timeout',
            'is the server running', 'accepting tcp/ip connections'
        ]):
            logger.error(f"Database connection error in handler500: {exception}")
            
            # Determine if this is an admin request
            is_admin = request.path.startswith('/admin/') if request else False
            
            # Render user-friendly error page
            try:
                html = render_to_string('database_error.html', {
                    'error_type': 'Database Connection Error',
                    'error_message': 'We are currently experiencing database connectivity issues. Please try again in a few moments.',
                    'support_message': 'If this problem persists, please contact support.',
                    'is_admin': is_admin,
                })
                return HttpResponseServerError(html)
            except Exception as template_error:
                # Fallback if template rendering fails
                logger.error(f"Error rendering database error template: {template_error}")
                home_link = '/admin/' if is_admin else '/'
                return HttpResponseServerError(
                    f'<html><body style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">'
                    f'<h1 style="color: #dc2626;">Service Temporarily Unavailable</h1>'
                    f'<p style="color: #6b7280; font-size: 18px;">We are currently experiencing database connectivity issues.</p>'
                    f'<p style="color: #6b7280;">Please try again in a few moments.</p>'
                    f'<p style="margin-top: 30px;"><a href="{home_link}" style="color: #2563eb; text-decoration: none;">Return to {"Admin" if is_admin else "Home"}</a></p>'
                    f'</body></html>',
                    content_type='text/html'
                )
    
    # For other 500 errors, show generic error page
    try:
        html = render_to_string('database_error.html', {
            'error_type': 'Internal Server Error',
            'error_message': 'An internal server error occurred. Please try again later.',
            'support_message': 'If this problem persists, please contact support.',
            'is_admin': request.path.startswith('/admin/') if request else False,
        })
        return HttpResponseServerError(html)
    except:
        # Ultimate fallback
        return HttpResponseServerError(
            '<html><body style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">'
            '<h1 style="color: #dc2626;">Internal Server Error</h1>'
            '<p style="color: #6b7280; font-size: 18px;">An error occurred. Please try again later.</p>'
            '<p style="margin-top: 30px;"><a href="/" style="color: #2563eb; text-decoration: none;">Return to Home</a></p>'
            '</body></html>',
            content_type='text/html'
        )

