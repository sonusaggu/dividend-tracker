"""
Simple Google OAuth 2.0 implementation without django-allauth
"""
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import login as django_login
from django.db import transaction
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def get_google_oauth_url(request, redirect_uri=None):
    """
    Generate Google OAuth authorization URL
    
    Args:
        request: Django request object
        redirect_uri: Callback URL after Google authentication (optional)
    
    Returns:
        str: Google OAuth authorization URL
    """
    from decouple import config
    import os
    
    client_id = config('GOOGLE_OAUTH_CLIENT_ID', default='')
    
    if not client_id:
        logger.warning("GOOGLE_OAUTH_CLIENT_ID not configured")
        return None
    
    # Get redirect URI - priority:
    # 1. Explicitly provided redirect_uri
    # 2. GOOGLE_OAUTH_REDIRECT_URI environment variable
    # 3. Render hostname (if available)
    # 4. Request's absolute URI (fallback)
    
    if not redirect_uri:
        # Try environment variable first
        redirect_uri = config('GOOGLE_OAUTH_REDIRECT_URI', default='')
        
        if not redirect_uri:
            # Try to use Render hostname (more reliable than custom domains)
            render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
            if render_hostname:
                redirect_uri = f"https://{render_hostname}/auth/google/callback/"
            else:
                # Fallback to request's absolute URI
                redirect_uri = request.build_absolute_uri('/auth/google/callback/')
                # If it's using dividend.forum and we have Render hostname, warn
                if 'dividend.forum' in redirect_uri and render_hostname:
                    logger.warning(f"Using dividend.forum for OAuth redirect. Consider using Render hostname: {render_hostname}")
    
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
    }
    
    # Build URL with query parameters
    from urllib.parse import urlencode
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    
    # Log the redirect URI for debugging
    logger.info(f"🔐 Google OAuth redirect URI: {redirect_uri}")
    logger.info(f"🔐 Google OAuth auth URL generated successfully")
    
    return auth_url


def exchange_code_for_token(code, redirect_uri):
    """
    Exchange authorization code for access token
    
    Args:
        code: Authorization code from Google
        redirect_uri: Callback URL (must match the one used in auth URL)
    
    Returns:
        dict: Token response with access_token, or None if error
    """
    from decouple import config
    
    client_id = config('GOOGLE_OAUTH_CLIENT_ID', default='')
    client_secret = config('GOOGLE_OAUTH_CLIENT_SECRET', default='')
    
    if not client_id or not client_secret:
        logger.error("Google OAuth credentials not configured")
        return None
    
    data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }
    
    try:
        response = requests.post(GOOGLE_TOKEN_URL, data=data, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error exchanging code for token: {e}")
        return None


def get_user_info(access_token):
    """
    Get user information from Google using access token
    
    Args:
        access_token: Google OAuth access token
    
    Returns:
        dict: User info with email, name, etc., or None if error
    """
    headers = {
        'Authorization': f'Bearer {access_token}',
    }
    
    try:
        response = requests.get(GOOGLE_USERINFO_URL, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting user info from Google: {e}")
        return None


def create_or_get_user(google_user_info):
    """
    Create or get user from Google user info
    
    Args:
        google_user_info: Dict with email, name, etc. from Google
    
    Returns:
        User: Django user object
    """
    email = google_user_info.get('email', '').lower().strip()
    first_name = google_user_info.get('given_name', '')
    last_name = google_user_info.get('family_name', '')
    google_id = google_user_info.get('id', '')
    
    if not email:
        logger.error("No email in Google user info")
        return None
    
    # Try to find existing user by email
    try:
        user = User.objects.get(email=email)
        # Update name if available
        if first_name and not user.first_name:
            user.first_name = first_name
        if last_name and not user.last_name:
            user.last_name = last_name
        user.save()
        
        # Mark email as verified for Google OAuth users (Google already verified it)
        try:
            from portfolio.models import EmailVerification
            from django.utils import timezone
            from django.utils.crypto import get_random_string
            
            verification, created = EmailVerification.objects.get_or_create(
                user=user,
                defaults={
                    'token': get_random_string(length=32),
                    'is_verified': True,
                    'verified_at': timezone.now(),
                }
            )
            if not created and not verification.is_verified:
                # Update existing unverified record to verified
                verification.is_verified = True
                verification.verified_at = timezone.now()
                verification.save()
                logger.info(f"Email verified for existing Google OAuth user: {email}")
        except Exception as e:
            logger.warning(f"Could not update EmailVerification for Google user: {e}")
        
        logger.info(f"Existing user logged in via Google: {email}")
        return user
    except User.DoesNotExist:
        # Create new user
        # Generate username from email
        base_username = email.split('@')[0]
        base_username = ''.join(c for c in base_username if c.isalnum() or c == '_')
        if len(base_username) < 3:
            base_username = base_username + '123'
        base_username = base_username[:27]
        
        # Ensure uniqueness
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            suffix = str(counter)
            max_len = 30 - len(suffix)
            username = base_username[:max_len] + suffix
            counter += 1
            if counter > 999:
                import random
                username = base_username[:20] + str(random.randint(1000, 9999))
                break
        
        # Create user
        # Generate a random password (user will use Google to login)
        from django.utils.crypto import get_random_string
        random_password = get_random_string(length=50)
        
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=random_password,
        )
        
        # Mark email as verified if Google verified it
        # You can add a custom field for this or use a flag
        
        logger.info(f"New user created via Google: {email} (username: {username})")
        return user

