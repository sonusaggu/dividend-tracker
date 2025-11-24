from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from portfolio.utils.email_validator import (
    validate_email_format, 
    validate_email_domain, 
    is_disposable_email,
    ALLOWED_EMAIL_DOMAINS
)

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        help_text='Required. Use Gmail, Outlook, Hotmail, Yahoo, iCloud, or other supported providers.'
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Tailwind classes to all fields
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary focus:border-primary'
            })
    
    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('An account with this email already exists. Please use a different email or try logging in.')
        
        # Validate email format
        is_valid, error = validate_email_format(email)
        if not is_valid:
            raise forms.ValidationError(error)
        
        # Validate email domain (must be from allowed providers, checks disposable emails too)
        is_valid, error = validate_email_domain(email)
        if not is_valid:
            raise forms.ValidationError(error)
        
        return email
    
    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken. Please choose another.')
        
        # Validate username format
        if len(username) < 3:
            raise forms.ValidationError('Username must be at least 3 characters long.')
        
        if len(username) > 30:
            raise forms.ValidationError('Username must be 30 characters or less.')
        
        # Check for invalid characters
        if not username.replace('_', '').replace('-', '').isalnum():
            raise forms.ValidationError('Username can only contain letters, numbers, hyphens, and underscores.')
        
        return username