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
            response_data = response.json()
            email_id = response_data.get('id', 'unknown')
            logger.info(f"Email sent via Resend to {to_email} (ID: {email_id})")
            return True, "Success"
        else:
            error_msg = response.text
            logger.error(f"Resend API failed ({response.status_code}): {error_msg}")
            # Check for domain verification error
            try:
                error_json = response.json()
                if 'message' in error_json and 'domain' in error_json.get('message', '').lower():
                    logger.warning("Resend domain verification issue - check Resend dashboard")
            except:
                pass
            return False, error_msg
    except Exception as e:
        logger.error(f"Resend API error: {e}")
        return False, str(e)


def send_email_via_smtp(to_email, subject, html_content, text_content=None):
    """Send email via SMTP (Django's default)"""
    try:
        from_email = settings.DEFAULT_FROM_EMAIL
        if not from_email:
            error_msg = "DEFAULT_FROM_EMAIL is not set in settings"
            logger.error(f"❌ {error_msg}")
            print(f"❌ [EMAIL_SERVICE] {error_msg}")
            return False, error_msg
        
        # Check if SMTP credentials are configured
        email_host_user = getattr(settings, 'EMAIL_HOST_USER', '')
        email_host_password = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
        
        if not email_host_user or not email_host_password:
            error_msg = f"SMTP credentials not configured. EMAIL_HOST_USER: {'SET' if email_host_user else 'NOT SET'}, EMAIL_HOST_PASSWORD: {'SET' if email_host_password else 'NOT SET'}"
            logger.error(f"❌ {error_msg}")
            print(f"❌ [EMAIL_SERVICE] {error_msg}")
            return False, error_msg
        
        logger.debug(f"SMTP: Sending email from {from_email} to {to_email}")
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content or strip_tags(html_content),
            from_email=from_email,
            to=[to_email]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        
        logger.info(f"Email sent via SMTP to {to_email}")
        return True, "Success"
    except Exception as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, str(e)


def send_email(to_email, subject, html_content, text_content=None):
    """
    Unified email sending function
    Tries Resend API first if configured, otherwise uses SMTP
    """
    logger.info(f"Attempting to send email to {to_email} with subject: {subject}")
    
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
        logger.error(f"Both Resend and SMTP failed for {to_email}. Last error: {message}")
        return False
