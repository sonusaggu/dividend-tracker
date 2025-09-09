from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.utils.html import strip_tags

def send_dividend_alert_email(user_email, stock_symbol, dividend_date, days_advance, 
                             dividend_amount, dividend_currency, dividend_frequency):
    subject = f"💰 Dividend Alert: {stock_symbol}"
    
    # HTML template
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dividend Alert</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                line-height: 1.6;
                color: #2D3748;
                background-color: #F5F7FA;
                margin: 0;
                padding: 20px;
            }}
            
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: white;
                border-radius: 16px;
                overflow: hidden;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05);
            }}
            
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 30px 20px;
                text-align: center;
                color: white;
            }}
            
            .logo {{
                font-size: 24px;
                font-weight: 700;
                margin-bottom: 10px;
            }}
            
            .title {{
                font-size: 28px;
                font-weight: 700;
                margin: 0;
            }}
            
            .subtitle {{
                font-size: 16px;
                opacity: 0.9;
                margin: 10px 0 0;
            }}
            
            .content {{
                padding: 30px;
            }}
            
            .card {{
                background: white;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
                border: 1px solid #E2E8F0;
            }}
            
            .info-grid {{
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 15px;
                margin-bottom: 25px;
            }}
            
            @media (max-width: 480px) {{
                .info-grid {{
                    grid-template-columns: 1fr;
                }}
            }}
            
            .info-item {{
                display: flex;
                align-items: center;
                padding: 15px;
                background: #F8FAFC;
                border-radius: 10px;
            }}
            
            .icon {{
                width: 40px;
                height: 40px;
                border-radius: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 15px;
                flex-shrink: 0;
            }}
            
            .icon-calendar {{
                background: #FFEDD5;
                color: #F97316;
            }}
            
            .icon-bell {{
                background: #DBEAFE;
                color: #3B82F6;
            }}
            
            .icon-cash {{
                background: #D1FAE5;
                color: #10B981;
            }}
            
            .icon-refresh {{
                background: #E0E7FF;
                color: #6366F1;
            }}
            
            .info-text {{
                font-size: 14px;
            }}
            
            .info-label {{
                display: block;
                font-weight: 500;
                margin-bottom: 4px;
            }}
            
            .info-value {{
                display: block;
                font-weight: 600;
                font-size: 16px;
                color: #1E293B;
            }}
            
            .amount-card {{
                background: linear-gradient(135deg, #10B981 0%, #059669 100%);
                color: white;
                text-align: center;
                padding: 25px;
                border-radius: 12px;
                margin: 25px 0;
            }}
            
            .amount-label {{
                font-size: 16px;
                margin-bottom: 8px;
                opacity: 0.9;
            }}
            
            .amount-value {{
                font-size: 32px;
                font-weight: 700;
                margin: 0;
            }}
            
            .currency {{
                font-size: 18px;
                font-weight: 500;
            }}
            
            .footer {{
                text-align: center;
                padding: 20px;
                background: #F8FAFC;
                border-top: 1px solid #E2E8F0;
                font-size: 14px;
                color: #64748B;
            }}
            
            .disclaimer {{
                font-size: 12px;
                color: #94A3B8;
                margin-top: 15px;
                line-height: 1.5;
            }}
            
            .button {{
                display: inline-block;
                background: #6366F1;
                color: white;
                text-decoration: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: 600;
                margin: 15px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Dividend Tracker</div>
                <h1 class="title">Dividend Alert</h1>
                <p class="subtitle">Your notification for {stock_symbol}</p>
            </div>
            
            <div class="content">
                <div class="info-grid">
                    <div class="info-item">
                        <div class="icon icon-calendar">📅</div>
                        <div class="info-text">
                            <span class="info-label">Dividend Date</span>
                            <span class="info-value">{dividend_date}</span>
                        </div>
                    </div>
                    
                    <div class="info-item">
                        <div class="icon icon-bell">⏰</div>
                        <div class="info-text">
                            <span class="info-label">Alert Setting</span>
                            <span class="info-value">{days_advance} day(s) in advance</span>
                        </div>
                    </div>
                    
                    <div class="info-item">
                        <div class="icon icon-cash">💰</div>
                        <div class="info-text">
                            <span class="info-label">Amount</span>
                            <span class="info-value">{dividend_amount} {dividend_currency}</span>
                        </div>
                    </div>
                    
                    <div class="info-item">
                        <div class="icon icon-refresh">🔄</div>
                        <div class="info-text">
                            <span class="info-label">Frequency</span>
                            <span class="info-value">{dividend_frequency}</span>
                        </div>
                    </div>
                </div>
                
                <div class="amount-card">
                    <div class="amount-label">Dividend Amount</div>
                    <div class="amount-value">{dividend_amount} <span class="currency">{dividend_currency}</span></div>
                </div>
                
                <div class="card">
                    <h3 style="margin-top: 0;">Next Steps</h3>
                    <p>Consider reviewing your investment strategy and ensuring you have sufficient shares to maximize your dividend income.</p>
                </div>
            </div>
            
            <div class="footer">
                <p>This is an automated alert from your dividend tracking service.</p>
                <p>Best regards,<br><strong>Dividend Tracker Team</strong></p>
                
                <div class="disclaimer">
                    Please do not reply to this email. If you have any questions, contact our support team through the app.
                    <br>© 2025 Dividend Tracker. All rights reserved.
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Create plain text version for email clients that don't support HTML
    text_content = f"""
    Dividend Alert for {stock_symbol}
    
    Dividend Date: {dividend_date}
    Alert Setting: {days_advance} day(s) in advance
    Amount: {dividend_amount} {dividend_currency}
    Frequency: {dividend_frequency}
    
    This is an automated alert from your dividend tracking service.
    
    Best regards,
    Dividend Tracker Team
    """
    
    # Create email message
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user_email]
    )
    
    # Attach HTML content
    email.attach_alternative(html_content, "text/html")
    
    # Send email
    email.send(fail_silently=False)