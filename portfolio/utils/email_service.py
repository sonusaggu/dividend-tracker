"""
Unified email service for Django using Resend API
Falls back to SMTP if Resend is not configured
"""
import logging
import requests
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.utils.html import strip_tags
from decouple import config

logger = logging.getLogger(__name__)

# Resend API Configuration
RESEND_API_KEY = config('RESEND_API_KEY', default='')
RESEND_FROM_EMAIL = config('RESEND_FROM_EMAIL', default='')
USE_RESEND = bool(RESEND_API_KEY and RESEND_FROM_EMAIL)


def send_email_via_resend(to_email, subject, html_content, text_content=None):
    """Send email via Resend API"""
    if not RESEND_API_KEY or not RESEND_FROM_EMAIL:
        return False, "Resend not configured"
    
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": RESEND_FROM_EMAIL,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
                "text": text_content or strip_tags(html_content)
            },
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"Email sent via Resend to {to_email}")
            return True, "Success"
        else:
            error_msg = response.text
            logger.error(f"Resend API failed ({response.status_code}): {error_msg}")
            return False, error_msg
    except Exception as e:
        logger.error(f"Resend API error: {e}")
        return False, str(e)


def send_email_via_smtp(to_email, subject, html_content, text_content=None):
    """Send email via SMTP (Django's default)"""
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content or strip_tags(html_content),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        logger.info(f"Email sent via SMTP to {to_email}")
        return True, "Success"
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        return False, str(e)


def send_email(to_email, subject, html_content, text_content=None):
    """
    Unified email sending function
    Tries Resend API first if configured, otherwise uses SMTP
    """
    # Try Resend API first if configured
    if USE_RESEND:
        success, message = send_email_via_resend(to_email, subject, html_content, text_content)
        if success:
            return True
        else:
            logger.warning(f"Resend failed: {message}, falling back to SMTP")
    
    # Fallback to SMTP
    success, message = send_email_via_smtp(to_email, subject, html_content, text_content)
    if success:
        return True
    else:
        logger.error(f"Both Resend and SMTP failed. Last error: {message}")
        return False
