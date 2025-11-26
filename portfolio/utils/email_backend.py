"""
Custom email backend for Django password reset
Uses Resend API if configured, otherwise falls back to SMTP
"""
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage, EmailMultiAlternatives
from django.core.mail import get_connection
from django.conf import settings
from decouple import config
import logging
import requests

logger = logging.getLogger(__name__)

# Resend API Configuration
RESEND_API_KEY = config('RESEND_API_KEY', default='')
RESEND_FROM_EMAIL = config('RESEND_FROM_EMAIL', default='')
USE_RESEND = bool(RESEND_API_KEY and RESEND_FROM_EMAIL)


class ResendEmailBackend(BaseEmailBackend):
    """
    Custom email backend that uses Resend API
    Falls back to SMTP if Resend is not configured
    """
    
    def send_messages(self, email_messages):
        """
        Send email messages using Resend API or SMTP fallback
        """
        if not email_messages:
            return 0
        
        num_sent = 0
        
        for message in email_messages:
            try:
                # Extract email data
                to_email = message.to[0] if message.to else None
                if not to_email:
                    continue
                
                subject = message.subject
                
                # Get HTML and text content
                html_content = None
                text_content = None
                
                if isinstance(message, EmailMultiAlternatives):
                    for content, content_type in message.alternatives:
                        if content_type == 'text/html':
                            html_content = content
                    text_content = message.body
                else:
                    text_content = message.body
                
                # Try Resend API first if configured
                if USE_RESEND:
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
                                "html": html_content or "",
                                "text": text_content or ""
                            },
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            logger.info(f"Email sent via Resend to {to_email}")
                            num_sent += 1
                            continue
                        else:
                            logger.warning(f"Resend API failed ({response.status_code}): {response.text}, falling back to SMTP")
                    except Exception as e:
                        logger.warning(f"Resend API error: {e}, falling back to SMTP")
                
                # Fallback to SMTP
                smtp_backend = get_connection(
                    backend='django.core.mail.backends.smtp.EmailBackend',
                    fail_silently=False
                )
                smtp_backend.send_messages([message])
                logger.info(f"Email sent via SMTP to {to_email}")
                num_sent += 1
                
            except Exception as e:
                logger.error(f"Error sending email: {e}")
                if not self.fail_silently:
                    raise
        
        return num_sent
