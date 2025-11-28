"""
Dividend alert email utility
Uses Resend API if configured, otherwise falls back to SMTP
"""
import logging
from django.conf import settings
import os
from portfolio.utils.email_service import send_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_site_url():
    """Get the site URL from settings or environment"""
    # First, try to get SITE_DOMAIN from settings (this is the primary source)
    site_domain = getattr(settings, 'SITE_DOMAIN', None)
    if site_domain:
        # Ensure it has protocol
        if not site_domain.startswith('http://') and not site_domain.startswith('https://'):
            # Default to https unless explicitly http
            site_domain = f"https://{site_domain}"
        return site_domain
    
    # Try to get from environment (Render.com sets this)
    render_url = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if render_url:
        return f"https://{render_url}"
    
    # Fallback to ALLOWED_HOSTS
    allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
    if allowed_hosts and allowed_hosts[0] != '*':
        host = allowed_hosts[0]
        # Skip localhost and 127.0.0.1
        if host not in ['localhost', '127.0.0.1']:
            # Remove port if present
            host = host.split(':')[0]
            # Check if it's a domain (not localhost)
            if '.' in host or host.startswith('dividend.forum'):
                return f"https://{host}"
    
    # Default fallback - use dividend.forum if available
    if 'dividend.forum' in allowed_hosts:
        return "https://dividend.forum"
    
    # Last resort - should not happen in production
    return "https://dividend.forum"


def send_dividend_alert_email(user_email, stock_symbol, dividend_date, days_advance, dividend_amount, dividend_currency, dividend_frequency):
    """
    Send dividend alert email using Resend API or SMTP fallback
    """
    site_url = get_site_url()
    stock_url = f"{site_url}/stocks/{stock_symbol}/"
    alerts_url = f"{site_url}/my-alerts/"
    
    subject = f"💰 Dividend Alert: {stock_symbol} ({days_advance} days early)"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                text-align: center;
                border-radius: 10px 10px 0 0;
            }}
            .content {{
                background: #f9f9f9;
                padding: 30px;
                border-radius: 0 0 10px 10px;
            }}
            .alert-card {{
                background: white;
                border-left: 4px solid #10B981;
                padding: 20px;
                margin: 20px 0;
                border-radius: 5px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .button {{
                display: inline-block;
                background: #667eea;
                color: white;
                text-decoration: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: 600;
                margin: 10px 5px;
            }}
            .button:hover {{
                background: #5568d3;
            }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                color: #666;
                font-size: 12px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>💰 Dividend Alert</h1>
            <p>Your notification for {stock_symbol}</p>
        </div>
        <div class="content">
            <div class="alert-card">
                <h2 style="margin-top: 0; color: #667eea;">{stock_symbol} Dividend Payment</h2>
                <p><strong>Dividend Amount:</strong> {dividend_amount} {dividend_currency}</p>
                <p><strong>Ex-Dividend Date:</strong> {dividend_date}</p>
                <p><strong>Frequency:</strong> {dividend_frequency}</p>
                <p><strong>Alert Sent:</strong> {days_advance} days in advance</p>
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{stock_url}" class="button">View Stock Details</a>
                <a href="{alerts_url}" class="button" style="background: #10B981;">Manage Alerts</a>
            </div>
            
            <div class="footer">
                <p>You're receiving this because you set up a dividend alert for {stock_symbol}.</p>
                <p><a href="{alerts_url}">Manage Your Alerts</a> | <a href="{site_url}">Visit StockFolio</a></p>
                <p>Copyright 2024 StockFolio. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
Dividend Alert: {stock_symbol}

{stock_symbol} is paying a dividend of {dividend_amount} {dividend_currency} on {dividend_date}.

Details:
- Frequency: {dividend_frequency}
- Alert sent: {days_advance} days in advance

View Stock: {stock_url}
Manage Alerts: {alerts_url}

You're receiving this because you set up a dividend alert for {stock_symbol}.

Best regards,
StockFolio
    """
    
    success = send_email(
        to_email=user_email,
        subject=subject,
        html_content=html_content,
        text_content=text_content
    )
    
    if success:
        logger.info(f"Dividend alert email sent to {user_email}")
        return True
    else:
        logger.error(f"Failed to send dividend alert email to {user_email}")
        return False
