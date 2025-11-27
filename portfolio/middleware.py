"""
Custom middleware for security and logging
"""
import logging
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin

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



