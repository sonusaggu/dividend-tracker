"""
Django management command to test email configuration
Tests Resend API and SMTP fallback
"""
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from decouple import config
from portfolio.utils.email_service import send_email, USE_RESEND, RESEND_API_KEY, RESEND_FROM_EMAIL
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Test email configuration (Resend API and SMTP fallback)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='Email address to send test email to',
            required=True
        )
    
    def handle(self, *args, **options):
        test_email = options['email']
        
        self.stdout.write("=" * 70)
        self.stdout.write("Testing Email Configuration")
        self.stdout.write("=" * 70)
        
        # Check Resend API configuration
        self.stdout.write("\n1. Resend API Configuration:")
        self.stdout.write(f"   RESEND_API_KEY: {'*' * 20 if RESEND_API_KEY else '(not set)'}")
        self.stdout.write(f"   RESEND_FROM_EMAIL: {RESEND_FROM_EMAIL or '(not set)'}")
        self.stdout.write(f"   Status: {'✓ Configured' if USE_RESEND else '✗ Not configured'}")
        
        # Test Resend API
        if USE_RESEND:
            self.stdout.write("\n2. Testing Resend API...")
            try:
                html_content = """
                <html>
                <body>
                    <h1>Test Email from StockFolio (Resend API)</h1>
                    <p>This is a test email sent via Resend API.</p>
                    <p>If you received this, your Resend API is working correctly!</p>
                    <p>Best regards,<br>StockFolio Team</p>
                </body>
                </html>
                """
                
                text_content = """Test Email from StockFolio (Resend API)

This is a test email sent via Resend API.

If you received this, your Resend API is working correctly!

Best regards,
StockFolio Team"""
                
                success = send_email(
                    to_email=test_email,
                    subject="Test Email from StockFolio (Resend API)",
                    html_content=html_content,
                    text_content=text_content
                )
                
                if success:
                    self.stdout.write(self.style.SUCCESS("   ✓ Resend API: SUCCESS"))
                else:
                    self.stdout.write(self.style.WARNING("   ⚠ Resend API: FAILED (will try SMTP fallback)"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"   ⚠ Resend API: ERROR - {e}"))
        else:
            self.stdout.write("\n2. Resend API: SKIPPED (not configured)")
        
        # Check SMTP configuration (fallback)
        self.stdout.write("\n3. SMTP Configuration (Fallback):")
        self.stdout.write(f"   EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"   EMAIL_HOST: {settings.EMAIL_HOST}")
        self.stdout.write(f"   EMAIL_PORT: {settings.EMAIL_PORT}")
        self.stdout.write(f"   EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"   EMAIL_HOST_USER: {settings.EMAIL_HOST_USER or '(not set)'}")
        self.stdout.write(f"   EMAIL_HOST_PASSWORD: {'*' * len(settings.EMAIL_HOST_PASSWORD) if settings.EMAIL_HOST_PASSWORD else '(not set)'}")
        self.stdout.write(f"   DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        
        # Test SMTP
        self.stdout.write("\n4. Testing SMTP (Fallback)...")
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            self.stdout.write(self.style.WARNING("   ⚠ SMTP credentials not set (skipping SMTP test)"))
        else:
            try:
                send_mail(
                    subject='Test Email from StockFolio (SMTP Fallback)',
                    message='This is a test email sent via SMTP fallback.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[test_email],
                    fail_silently=False,
                )
                self.stdout.write(self.style.SUCCESS("   ✓ SMTP: SUCCESS"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ✗ SMTP: FAILED - {e}"))
                import traceback
                self.stdout.write(traceback.format_exc())
        
        # Summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("Test Summary")
        self.stdout.write("=" * 70)
        self.stdout.write(f"\nTest email sent to: {test_email}")
        self.stdout.write(f"Check your inbox (and spam folder) for test emails.")
        
        if USE_RESEND:
            self.stdout.write(self.style.SUCCESS("\n✓ Resend API is configured"))
            self.stdout.write("  Primary method: Resend API")
            self.stdout.write("  Fallback method: SMTP")
            self.stdout.write("\n  Note: Resend requires a verified domain for production use.")
            self.stdout.write("  For testing, you can use the Resend test domain.")
        else:
            self.stdout.write(self.style.WARNING("\n⚠ Resend API is not configured"))
            self.stdout.write("  Using: SMTP only")
            self.stdout.write("\n  To enable Resend API, set:")
            self.stdout.write("    RESEND_API_KEY=your_resend_api_key")
            self.stdout.write("    RESEND_FROM_EMAIL=your_verified_email@yourdomain.com")
            self.stdout.write("\n  Get your API key from: https://resend.com/api-keys")
        
        self.stdout.write("\n💡 Tips:")
        self.stdout.write("  - For Gmail SMTP: Use App Password (not regular password)")
        self.stdout.write("  - Resend API: Requires verified domain for production")
        self.stdout.write("  - Check Render logs for detailed error messages")
