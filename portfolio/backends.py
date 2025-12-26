"""
Custom authentication backends
"""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """
    Custom authentication backend that allows users to login with either
    their username or email address.
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user by username or email
        """
        if username is None:
            username = kwargs.get('username')
        
        if username is None or password is None:
            return None
        
        try:
            # Try to find user by username or email (case-insensitive)
            user = User.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
        except User.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # If multiple users found (shouldn't happen with proper constraints),
            # get the first one
            user = User.objects.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            ).first()
        
        # Check password
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        
        return None

