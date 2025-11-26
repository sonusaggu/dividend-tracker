"""
Email verification utility for sending verification emails
Uses Resend API if configured, otherwise falls back to SMTP
"""
import secrets
import logging
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from portfolio.utils.email_service import send_email

logger = logging.getLogger(__name__)


def generate_verification_token():
    """Generate a secure random token for email verification"""
    return secrets.token_urlsafe(32)


def send_verification_email(user, token):
    """
    Send email verification email to user
    Uses Resend API if configured, otherwise falls back to SMTP
    """
    try:
        # Get site domain
        site_domain = getattr(settings, 'SITE_DOMAIN', 'https://dividend.forum')
        verification_url = f"{site_domain}/verify-email/{token}/"
        
        # Prepare email context
        context = {
            'user': user,
            'verification_url': verification_url,
            'site_name': 'StockFolio',
        }
        
        # Render email templates
        subject = 'Verify Your StockFolio Account'
        html_message = render_to_string('email_verification.html', context)
        plain_message = strip_tags(html_message)
        
        # Use unified email service (Resend or SMTP)
        success = send_email(
            to_email=user.email,
            subject=subject,
            html_content=html_message,
            text_content=plain_message
        )
        
        if success:
            logger.info(f"Verification email sent to {user.email}")
            return True
        else:
            logger.error(f"Failed to send verification email to {user.email}")
            return False
        
    except Exception as e:
        logger.error(f"Error sending verification email to {user.email}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def create_verification_token(user):
    """
    Create or update email verification token for user
    Returns the EmailVerification object
    """
    from portfolio.models import EmailVerification
    from django.utils import timezone
    
    token = generate_verification_token()
    
    # Create or update verification record
    verification, created = EmailVerification.objects.update_or_create(
        user=user,
        defaults={
            'token': token,
            'is_verified': False,
            'verified_at': None,
        }
    )
    
    return verification
