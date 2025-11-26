"""
Dividend alert email utility
Uses Resend API if configured, otherwise falls back to SMTP
"""
import logging
from portfolio.utils.email_service import send_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_dividend_alert_email(user_email, stock_symbol, dividend_date, days_advance, dividend_amount, dividend_currency, dividend_frequency):
    """
    Send dividend alert email using Resend API or SMTP fallback
    """
    subject = f"{stock_symbol} Dividend Alert ({days_advance} days early)"
    
    html_content = f"""
    <html>
    <body>
        <p>Hello,</p>
        <p><strong>{stock_symbol}</strong> is paying a dividend of <strong>{dividend_amount} {dividend_currency}</strong> on <strong>{dividend_date}</strong>.</p>
        <p>This alert was sent {days_advance} days in advance.</p>
        <p>Frequency: {dividend_frequency}</p>
        <p>Best regards,<br>StockFolio</p>
    </body>
    </html>
    """
    
    text_content = f"""
Hello,

{stock_symbol} is paying a dividend of {dividend_amount} {dividend_currency} on {dividend_date}.

This alert was sent {days_advance} days in advance.
Frequency: {dividend_frequency}

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
