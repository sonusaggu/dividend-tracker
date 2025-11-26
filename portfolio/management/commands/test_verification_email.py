"""
Django management command to test verification email sending
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from portfolio.utils.email_verification import send_verification_email, create_verification_token
from portfolio.models import EmailVerification
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Test verification email sending'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='Email address to send verification email to',
            required=True
        )
        parser.add_argument(
            '--username',
            type=str,
            help='Username for the test user (will create if not exists)',
            default='test_user'
        )
    
    def handle(self, *args, **options):
        test_email = options['email']
        username = options['username']
        
        self.stdout.write("=" * 70)
        self.stdout.write("Testing Verification Email")
        self.stdout.write("=" * 70)
        
        # Get or create test user
        try:
            user = User.objects.get(email=test_email)
            self.stdout.write(f"✓ Found existing user: {user.username}")
        except User.DoesNotExist:
            try:
                user = User.objects.get(username=username)
                user.email = test_email
                user.save()
                self.stdout.write(f"✓ Updated user {username} with email {test_email}")
            except User.DoesNotExist:
                user = User.objects.create_user(
                    username=username,
                    email=test_email,
                    password='test_password_123'
                )
                self.stdout.write(f"✓ Created test user: {username}")
        
        # Check EmailVerification table
        self.stdout.write("\n1. Checking EmailVerification table...")
        try:
            EmailVerification.objects.first()
            self.stdout.write(self.style.SUCCESS("   ✓ EmailVerification table exists"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ EmailVerification table error: {e}"))
            self.stdout.write("   Run: python manage.py migrate portfolio")
            return
        
        # Create verification token
        self.stdout.write("\n2. Creating verification token...")
        try:
            verification = create_verification_token(user)
            self.stdout.write(self.style.SUCCESS(f"   ✓ Token created: {verification.token[:20]}..."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Error creating token: {e}"))
            import traceback
            self.stdout.write(traceback.format_exc())
            return
        
        # Send verification email
        self.stdout.write("\n3. Sending verification email...")
        try:
            success = send_verification_email(user, verification.token)
            if success:
                self.stdout.write(self.style.SUCCESS(f"   ✓ Verification email sent to {test_email}"))
                self.stdout.write(f"\n   Check {test_email} for the verification email.")
                self.stdout.write(f"   Verification URL: https://dividend.forum/verify-email/{verification.token}/")
            else:
                self.stdout.write(self.style.ERROR(f"   ✗ Failed to send verification email"))
                self.stdout.write("   Check logs above for error details.")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Exception: {e}"))
            import traceback
            self.stdout.write(traceback.format_exc())
        
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("Test Complete")
        self.stdout.write("=" * 70)
        self.stdout.write("\n💡 Tips:")
        self.stdout.write("  - Check your email inbox (and spam folder)")
        self.stdout.write("  - Verify Resend API key is set (or SMTP credentials)")
        self.stdout.write("  - Check Django logs for detailed error messages")
        self.stdout.write("  - Run 'python manage.py test_email --email your@email.com' to test general email")

