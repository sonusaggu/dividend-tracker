"""
Email validation utility to check if email addresses are authentic and valid
"""
import re
import socket
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# List of known disposable email domains
DISPOSABLE_EMAIL_DOMAINS = [
    '10minutemail.com', 'tempmail.com', 'guerrillamail.com', 'mailinator.com',
    'throwaway.email', 'temp-mail.org', 'getnada.com', 'mohmal.com',
    'fakeinbox.com', 'trashmail.com', 'yopmail.com', 'sharklasers.com',
    'grr.la', 'guerrillamailblock.com', 'pokemail.net', 'spam4.me',
    'bccto.me', 'chammy.info', 'devnullmail.com', 'maildrop.cc',
    'mintemail.com', 'mytemp.email', 'tempail.com', 'tempinbox.co.uk',
    'tmpmail.org', 'getairmail.com', 'mailcatch.com', 'meltmail.com',
    'melt.li', 'mintemail.com', 'mohmal.com', 'mytrashmail.com',
    'putthisinyourspamdatabase.com', 'spamgourmet.com', 'spamhole.com',
    'spamtraps.com', 'temp-mail.ru', 'tempe-mail.com', 'tempinbox.com',
    'throwawaymail.com', 'tmail.ws', 'trash-amil.com', 'trashmail.net',
    'trashymail.com', 'tyldd.com', 'wh4f.org', 'willselfdestruct.com',
    'zippymail.info', 'zoemail.org', '0-mail.com', '33mail.com',
    '4warding.com', '4warding.net', '4warding.org', 'emailmiser.com',
    'emailwarden.com', 'emailx.at', 'emailxfer.com', 'emkei.cf',
    'fakemailgenerator.com', 'fakemailz.com', 'fakemailz.net',
    'fakemailz.org', 'fakemailz.us', 'fakemailz.ws', 'fakemailz.info',
    'fakemailz.biz', 'fakemailz.co.uk', 'fakemailz.com.au',
]

# Allowed email domains (trusted providers)
ALLOWED_EMAIL_DOMAINS = [
    'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'hotmail.ca',
    'hotmail.co.uk', 'live.com', 'msn.com', 'yahoo.com', 'yahoo.ca',
    'yahoo.co.uk', 'yahoo.com.au', 'icloud.com', 'me.com', 'mac.com',
    'protonmail.com', 'proton.me', 'aol.com', 'zoho.com', 'mail.com',
    'gmx.com', 'yandex.com', 'mail.ru', 'qq.com', '163.com',
    'sbcglobal.net', 'att.net', 'verizon.net', 'comcast.net', 'cox.net',
    'earthlink.net', 'charter.net', 'optonline.net', 'rocketmail.com',
    'rediffmail.com', 'inbox.com', 'fastmail.com', 'tutanota.com',
]


def check_mx_record(domain: str) -> bool:
    """
    Check if domain has valid MX (Mail Exchange) records
    Returns True if domain has MX records, False otherwise
    """
    try:
        # Try to get MX records for the domain
        import dns.resolver
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            return len(mx_records) > 0
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return False
    except ImportError:
        # Fallback to socket-based check if dnspython is not available
        try:
            socket.getaddrinfo(domain, None)
            # Try common mail ports
            try:
                socket.create_connection((domain, 25), timeout=2)
                return True
            except (socket.timeout, socket.error, OSError):
                # Domain exists but might not have mail server on port 25
                # This is a basic check - not perfect but better than nothing
                return True
        except (socket.gaierror, OSError):
            return False
    except Exception as e:
        logger.debug(f"Error checking MX record for {domain}: {e}")
        return False


def is_disposable_email(email: str) -> bool:
    """Check if email is from a disposable email service"""
    domain = email.split('@')[-1].lower() if '@' in email else ''
    return domain in DISPOSABLE_EMAIL_DOMAINS


def validate_email_format(email: str) -> Tuple[bool, str]:
    """
    Validate email format using regex
    Returns (is_valid, error_message)
    """
    if not email or not email.strip():
        return False, 'Email address is required.'
    
    email = email.strip().lower()
    
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        return False, 'Please enter a valid email address.'
    
    # Check for common typos
    if '..' in email or email.startswith('.') or email.endswith('.'):
        return False, 'Email address contains invalid characters.'
    
    if email.count('@') != 1:
        return False, 'Email address must contain exactly one @ symbol.'
    
    return True, ''


def validate_email_domain(email: str) -> Tuple[bool, str]:
    """
    Validate email domain - check if it's allowed and not disposable
    Returns (is_valid, error_message)
    """
    if '@' not in email:
        return False, 'Invalid email format.'
    
    domain = email.split('@')[-1].lower().strip()
    
    # Check if it's a disposable email first
    if is_disposable_email(email):
        return False, 'Disposable email addresses are not allowed. Please use a permanent email address from a trusted provider.'
    
    # Check if domain is in allowed list
    if domain not in ALLOWED_EMAIL_DOMAINS:
        # Provide a helpful error message with examples
        examples = ', '.join(ALLOWED_EMAIL_DOMAINS[:5])
        return False, f'Please use a supported email provider. Examples: {examples}, and others. Disposable emails are not allowed.'
    
    return True, ''


def validate_email_authentic(email: str, check_mx: bool = True) -> Tuple[bool, str]:
    """
    Comprehensive email validation
    Checks format, domain, and optionally MX records
    Returns (is_valid, error_message)
    """
    # Step 1: Format validation
    is_valid, error = validate_email_format(email)
    if not is_valid:
        return False, error
    
    # Step 2: Domain validation
    is_valid, error = validate_email_domain(email)
    if not is_valid:
        return False, error
    
    # Step 3: MX record check (optional, can be slow)
    if check_mx:
        domain = email.split('@')[-1].lower()
        if not check_mx_record(domain):
            # Don't fail registration if MX check fails - domain might still be valid
            # Just log it for monitoring
            logger.warning(f"MX record check failed for {domain}, but allowing registration")
    
    return True, ''

