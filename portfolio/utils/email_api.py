import requests
import logging
from django.conf import settings
from decouple import config

RESEND_API_KEY = config('RESEND_API_KEY', default='')
FROM_EMAIL = config('RESEND_FROM_EMAIL', default='tritonxinc@gmail.com')

def send_dividend_alert_email(user_email, stock_symbol, dividend_date, days_advance, dividend_amount, dividend_currency, dividend_frequency):
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": f"Dividend Alerts <{FROM_EMAIL}>",
                "to": [user_email],
                "subject": f"{stock_symbol} Dividend Alert ({days_advance} days early)",
                "html": f"""
                    <p>Hello,</p>
                    <p>{stock_symbol} is paying a dividend of {dividend_amount} {dividend_currency} on {dividend_date}.</p>
                    <p>This alert was sent {days_advance} days in advance.</p>
                    <p>Frequency: {dividend_frequency}</p>
                    <p>Best regards,<br>Your App</p>
                """
            }
        )

        if response.status_code == 202:
            logging.info(f"Email sent to {user_email}")
        else:
            logging.error(f"Failed to send email: {response.text}")

    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")
