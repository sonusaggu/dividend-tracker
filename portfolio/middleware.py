"""
Custom middleware for security and logging
"""
import logging
import time
import re
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser

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
            
            # Get country from IP (basic detection, can be enhanced with GeoIP)
            country = self._get_country_from_ip(ip_address)
            
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
                )
            except Exception as db_error:
                # If there's still a database error, log it but don't break the request
                logger.error(f"Database error creating WebsiteMetric: {db_error}")
                logger.debug(f"session_key value: {repr(session_key)}, type: {type(session_key)}")
                raise  # Re-raise to be caught by outer try-except
            
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
    
    def _get_country_from_ip(self, ip_address):
        """Get country code from IP address (basic implementation)"""
        # This is a placeholder - in production, use a GeoIP library like geoip2
        # For now, return empty string
        # You can integrate with MaxMind GeoIP2 or similar service
        return ''



