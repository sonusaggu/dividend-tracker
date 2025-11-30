"""
Custom middleware for security and logging
"""
import logging
import time
import re
from django.http import HttpResponse, HttpResponseServerError
from django.template.loader import render_to_string
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from django.db import OperationalError, DatabaseError, InterfaceError

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Add security headers to all responses"""
    
    def process_response(self, request, response):
        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        # Block common exploit paths
        if any(path in request.path for path in [
            '/wp-admin', '/wp-content', '/wp-includes', '/xmlrpc.php',
            '/.git', '/.env', '/phpmyadmin', '/adminer.php'
        ]):
            logger.warning(f"Blocked suspicious path: {request.path} from {request.META.get('REMOTE_ADDR')}")
            return HttpResponse('Not Found', status=404)
        
        return response


class BlockSuspiciousUserAgentsMiddleware(MiddlewareMixin):
    """Block requests from suspicious user agents"""
    
    SUSPICIOUS_AGENTS = [
        'sqlmap', 'nikto', 'nmap', 'masscan', 'zap', 'burp',
        'w3af', 'acunetix', 'nessus', 'openvas'
    ]
    
    def process_request(self, request):
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        if any(suspicious in user_agent for suspicious in self.SUSPICIOUS_AGENTS):
            logger.warning(f"Blocked suspicious user agent: {user_agent} from {request.META.get('REMOTE_ADDR')}")
            return HttpResponse('Forbidden', status=403)
        
        return None


class DatabaseErrorHandlerMiddleware(MiddlewareMixin):
    """Handle database connection errors gracefully with user-friendly messages"""
    
    def process_exception(self, request, exception):
        """Catch database connection errors and return user-friendly error page"""
        if isinstance(exception, (OperationalError, DatabaseError, InterfaceError)):
            # Check if it's a connection error
            error_str = str(exception).lower()
            if any(keyword in error_str for keyword in [
                'connection refused', 'connection', 'server', 'tcp/ip',
                'could not connect', 'unable to connect', 'connection timeout',
                'is the server running', 'accepting tcp/ip connections'
            ]):
                logger.error(f"Database connection error in process_exception: {exception}")
                return self._render_database_error(request, exception)
        
        # Return None to let Django handle other exceptions normally
        return None
    
    def _render_database_error(self, request, exception):
        """Render the database error page"""
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


class WebsiteMetricsMiddleware(MiddlewareMixin):
    """Track website metrics for analytics"""
    
    # Paths to exclude from tracking
    EXCLUDED_PATHS = [
        '/static/',
        '/media/',
        '/admin/',
        '/favicon.ico',
        '/robots.txt',
        '/health/',
        '/api/health/',
    ]
    
    # Bot user agents
    BOT_AGENTS = [
        'bot', 'crawler', 'spider', 'scraper', 'googlebot', 'bingbot',
        'slurp', 'duckduckbot', 'baiduspider', 'yandexbot', 'sogou',
        'exabot', 'facebot', 'ia_archiver', 'archive.org_bot'
    ]
    
    def process_request(self, request):
        """Store request start time for response time calculation"""
        request._metrics_start_time = time.time()
        return None
    
    def process_response(self, request, response):
        """Track website metrics"""
        try:
            # Skip tracking for excluded paths
            if any(request.path.startswith(path) for path in self.EXCLUDED_PATHS):
                return response
            
            # Skip tracking for non-HTML responses (API, JSON, etc.)
            content_type = response.get('Content-Type', '')
            if 'text/html' not in content_type and response.status_code != 200:
                return response
            
            # Get user information
            user = None if isinstance(request.user, AnonymousUser) else request.user
            # Get session key safely - may not exist for all requests
            # Use empty string instead of None to work with current DB constraint
            session_key = ''
            if hasattr(request, 'session') and request.session:
                try:
                    sk = request.session.session_key
                    # Ensure it's always a string, never None
                    session_key = str(sk) if sk is not None else ''
                except (AttributeError, KeyError, TypeError):
                    session_key = ''
            
            # Final safety check - ensure session_key is never None
            if session_key is None:
                session_key = ''
            
            # Get request information
            ip_address = self._get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            referrer = request.META.get('HTTP_REFERER', '')
            
            # Detect if mobile
            is_mobile = self._is_mobile(user_agent)
            
            # Detect if bot
            is_bot = self._is_bot(user_agent)
            
            # Skip tracking bots if desired (uncomment to enable)
            # if is_bot:
            #     return response
            
            # Calculate response time
            response_time_ms = None
            if hasattr(request, '_metrics_start_time'):
                response_time = (time.time() - request._metrics_start_time) * 1000
                response_time_ms = int(response_time)
            
            # Get location from IP (country, city, region, timezone)
            location_data = self._get_location_from_ip(ip_address)
            country = location_data.get('country', '')
            city = location_data.get('city', '')
            region = location_data.get('region', '')
            timezone = location_data.get('timezone', '')
            
            # Import here to avoid circular imports
            from portfolio.models import WebsiteMetric
            
            # Final safety check - ensure session_key is a string
            session_key = str(session_key) if session_key is not None else ''
            
            # Create metric record
            try:
                WebsiteMetric.objects.create(
                    user=user,
                    session_key=session_key,
                    ip_address=ip_address,
                    user_agent=user_agent[:500],  # Limit length
                    referrer=referrer[:500],
                    path=request.path[:500],
                    method=request.method,
                    status_code=response.status_code,
                    response_time_ms=response_time_ms,
                    is_authenticated=user is not None,
                    is_mobile=is_mobile,
                    is_bot=is_bot,
                    country=country,
                    city=city,
                    region=region,
                    timezone=timezone,
                )
            except (OperationalError, DatabaseError, InterfaceError) as db_error:
                # If there's a database connection error, log it but don't break the request
                error_str = str(db_error).lower()
                if any(keyword in error_str for keyword in [
                    'connection refused', 'connection', 'server', 'tcp/ip',
                    'could not connect', 'unable to connect', 'connection timeout'
                ]):
                    logger.warning(f"Database connection error in metrics tracking (non-critical): {db_error}")
                    # Don't re-raise - just skip metrics tracking
                else:
                    logger.error(f"Database error creating WebsiteMetric: {db_error}")
                    logger.debug(f"session_key value: {repr(session_key)}, type: {type(session_key)}")
            except Exception as db_error:
                # For other errors, log but don't break the request
                logger.error(f"Error creating WebsiteMetric: {db_error}")
                logger.debug(f"session_key value: {repr(session_key)}, type: {type(session_key)}")
            
            # Update or create user session (only if session_key exists and is not empty)
            if session_key and session_key.strip():
                try:
                    from portfolio.models import UserSession
                    session, created = UserSession.objects.get_or_create(
                        session_key=session_key,
                        defaults={
                            'user': user,
                            'ip_address': ip_address,
                            'user_agent': user_agent[:500],
                            'referrer': referrer[:500],
                            'country': country,
                        }
                    )
                    if not created:
                        # Update existing session
                        session.last_activity = timezone.now()
                        session.page_views += 1
                        session.save(update_fields=['last_activity', 'page_views'])
                except (OperationalError, DatabaseError, InterfaceError) as e:
                    # Log database connection errors but don't break the request
                    error_str = str(e).lower()
                    if any(keyword in error_str for keyword in [
                        'connection refused', 'connection', 'server', 'tcp/ip',
                        'could not connect', 'unable to connect', 'connection timeout'
                    ]):
                        logger.debug(f"Database connection error updating user session (non-critical): {e}")
                    else:
                        logger.debug(f"Database error updating user session: {e}")
                except Exception as e:
                    # Log but don't break the request
                    logger.debug(f"Error updating user session: {e}")
            
        except Exception as e:
            # Log error but don't break the request
            logger.error(f"Error tracking website metrics: {e}", exc_info=True)
        
        return response
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def _is_mobile(self, user_agent):
        """Detect if user agent is mobile"""
        if not user_agent:
            return False
        mobile_patterns = [
            'mobile', 'android', 'iphone', 'ipad', 'ipod',
            'blackberry', 'windows phone', 'opera mini'
        ]
        user_agent_lower = user_agent.lower()
        return any(pattern in user_agent_lower for pattern in mobile_patterns)
    
    def _is_bot(self, user_agent):
        """Detect if user agent is a bot"""
        if not user_agent:
            return False
        user_agent_lower = user_agent.lower()
        return any(bot in user_agent_lower for bot in self.BOT_AGENTS)
    
    def _get_location_from_ip(self, ip_address):
        """Get location data from IP address (country, city, region, timezone)"""
        if not ip_address or ip_address in ['127.0.0.1', 'localhost', '::1']:
            return {'country': '', 'city': '', 'region': '', 'timezone': ''}
        
        try:
            # Use free ip-api.com service (45 requests/minute free tier)
            import requests
            url = f"http://ip-api.com/json/{ip_address}?fields=status,message,country,countryCode,region,regionName,city,timezone"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    return {
                        'country': data.get('countryCode', ''),
                        'city': data.get('city', ''),
                        'region': data.get('regionName', ''),
                        'timezone': data.get('timezone', '')
                    }
        except Exception as e:
            logger.debug(f"Could not get location from ip-api.com for IP {ip_address}: {e}")
        
        # Fallback: try ipapi.co
        try:
            url = f"https://ipapi.co/{ip_address}/json/"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                data = response.json()
                if not data.get('error'):
                    return {
                        'country': data.get('country_code', ''),
                        'city': data.get('city', ''),
                        'region': data.get('region', ''),
                        'timezone': data.get('timezone', '')
                    }
        except Exception as e:
            logger.debug(f"Fallback location lookup failed for IP {ip_address}: {e}")
        
        return {'country': '', 'city': '', 'region': '', 'timezone': ''}
    
    def _get_country_from_ip(self, ip_address):
        """Get country code from IP address (legacy method, kept for compatibility)"""
        location = self._get_location_from_ip(ip_address)
        return location.get('country', '')



