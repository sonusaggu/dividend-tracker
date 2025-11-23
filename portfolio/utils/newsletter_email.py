"""
Newsletter Email Sending Utility
Uses Django's built-in email backend (SMTP) - works with Gmail, Outlook, etc.
"""
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from portfolio.models import NewsletterSubscription
from portfolio.utils.newsletter_utils import DividendNewsletterGenerator
from django.utils import timezone
import logging
import os

logger = logging.getLogger(__name__)


def get_site_url():
    """Get the site URL from settings or environment"""
    # Try to get from environment (Render.com sets this)
    render_url = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if render_url:
        return f"https://{render_url}"
    
    # Fallback to ALLOWED_HOSTS or default
    allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
    if allowed_hosts and allowed_hosts[0] != '*':
        host = allowed_hosts[0]
        # Remove port if present
        host = host.split(':')[0]
        return f"https://{host}"
    
    # Default fallback
    return "https://your-app-name.onrender.com"


def send_newsletter_email(user, newsletter_content):
    """
    Send newsletter email to a single user using Django's email backend
    Works with Gmail, Outlook, and other SMTP providers
    """
    try:
        # Generate HTML email content
        html_content = generate_newsletter_html(newsletter_content)
        text_content = generate_newsletter_text(newsletter_content)
        
        # Create email
        subject = f"Weekly Dividend Newsletter - {newsletter_content['week_start'].strftime('%B %d, %Y')}"
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
        
        # Attach HTML version
        email.attach_alternative(html_content, "text/html")
        
        # Send email
        email.send()
        
        logger.info(f"Newsletter sent successfully to {user.email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending newsletter to {user.email}: {e}")
        return False


def generate_newsletter_html(content):
    """
    Generate HTML email content for newsletter
    """
    site_url = get_site_url()
    
    html = f"""
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
            .stock-card {{
                background: white;
                border-left: 4px solid #667eea;
                padding: 15px;
                margin: 15px 0;
                border-radius: 5px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .stock-header {{
                font-size: 18px;
                font-weight: bold;
                color: #667eea;
                margin-bottom: 10px;
            }}
            .stats {{
                background: white;
                padding: 20px;
                margin: 20px 0;
                border-radius: 5px;
                text-align: center;
            }}
            .stat-item {{
                display: inline-block;
                margin: 10px 20px;
            }}
            .stat-value {{
                font-size: 24px;
                font-weight: bold;
                color: #667eea;
            }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                color: #666;
                font-size: 12px;
            }}
            .button {{
                display: inline-block;
                padding: 12px 30px;
                background: #667eea;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 Weekly Dividend Newsletter</h1>
            <p>Week of {content['week_start'].strftime('%B %d')} - {content['week_end'].strftime('%B %d, %Y')}</p>
        </div>
        
        <div class="content">
            <h2>Top Dividend Opportunities</h2>
            <p>Here are the top dividend stocks for this week based on your <strong>{content['strategy_used'].replace('_', ' ').title()}</strong> strategy:</p>
            
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-value">{content['statistics']['total_stocks']}</div>
                    <div>Stocks</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{content['statistics']['average_yield']}%</div>
                    <div>Avg Yield</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{content['statistics']['highest_yield']}%</div>
                    <div>Highest Yield</div>
                </div>
            </div>
            
            <h3>Featured Stocks:</h3>
    """
    
    # Add stock cards
    for stock in content['top_stocks']:
        html += f"""
            <div class="stock-card">
                <div class="stock-header">{stock['symbol']} - {stock['company_name']}</div>
                <p><strong>Dividend:</strong> ${stock['dividend_amount']:.2f} ({stock['dividend_yield']*100:.2f}% yield)</p>
                <p><strong>Ex-Date:</strong> {stock['ex_dividend_date'].strftime('%B %d, %Y')} ({stock['days_until']} days)</p>
                <p><strong>Frequency:</strong> {stock['frequency']}</p>
                {f"<p><strong>Current Price:</strong> ${stock['current_price']:.2f}</p>" if stock.get('current_price') else ""}
                {f"<p><strong>P/E Ratio:</strong> {stock['pe_ratio']:.2f}</p>" if stock.get('pe_ratio') else ""}
                {f"<p><strong>Sector:</strong> {stock['sector']}</p>" if stock.get('sector') else ""}
            </div>
        """
    
    html += f"""
            <div style="text-align: center; margin: 30px 0;">
                <a href="{site_url}/all-stocks/" class="button">View All Stocks</a>
            </div>
            
            <div class="footer">
                <p>You're receiving this because you subscribed to our dividend newsletter.</p>
                <p><a href="{site_url}/newsletter/">Manage Subscription</a> | <a href="{site_url}/newsletter/?unsubscribe=1">Unsubscribe</a></p>
                <p>&copy; {content['generated_date'].year} StockFolio. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


def generate_newsletter_text(content):
    """
    Generate plain text version of newsletter
    """
    site_url = get_site_url()
    text = f"""
WEEKLY DIVIDEND NEWSLETTER
Week of {content['week_start'].strftime('%B %d')} - {content['week_end'].strftime('%B %d, %Y')}

Top Dividend Opportunities
Strategy: {content['strategy_used'].replace('_', ' ').title()}

Statistics:
- Total Stocks: {content['statistics']['total_stocks']}
- Average Yield: {content['statistics']['average_yield']}%
- Highest Yield: {content['statistics']['highest_yield']}%
- Lowest Yield: {content['statistics']['lowest_yield']}%

Featured Stocks:
"""
    
    for i, stock in enumerate(content['top_stocks'], 1):
        text += f"""
{i}. {stock['symbol']} - {stock['company_name']}
   Dividend: ${stock['dividend_amount']:.2f} ({stock['dividend_yield']*100:.2f}% yield)
   Ex-Date: {stock['ex_dividend_date'].strftime('%B %d, %Y')} ({stock['days_until']} days)
   Frequency: {stock['frequency']}
"""
        if stock.get('current_price'):
            text += f"   Current Price: ${stock['current_price']:.2f}\n"
        if stock.get('pe_ratio'):
            text += f"   P/E Ratio: {stock['pe_ratio']:.2f}\n"
        if stock.get('sector'):
            text += f"   Sector: {stock['sector']}\n"
    
    text += f"""
---
Manage your subscription: {site_url}/newsletter/
Unsubscribe: {site_url}/newsletter/?unsubscribe=1
"""
    
    return text


def send_newsletter_to_subscribers(dry_run=False):
    """
    Send newsletter to all active subscribers based on their frequency settings
    Returns count of emails sent
    """
    from datetime import timedelta
    
    try:
        # Get all active subscribers
        subscribers = NewsletterSubscription.objects.filter(is_active=True).select_related('user')
        
        if not subscribers.exists():
            logger.info("No active newsletter subscribers found")
            return 0
        
        # Generate newsletter content (base content, will be customized per user)
        generator = DividendNewsletterGenerator()
        base_content = generator.generate_newsletter_content()
        
        sent_count = 0
        failed_count = 0
        skipped_count = 0
        now = timezone.now()
        
        for subscription in subscribers:
            if not subscription.user.email:
                logger.warning(f"User {subscription.user.username} has no email address")
                continue
            
            # Check if it's time to send based on frequency
            should_send = False
            if not subscription.last_sent:
                # Never sent before, send now
                should_send = True
            else:
                # Check frequency
                days_since_last = (now - subscription.last_sent).days
                
                if subscription.frequency == 'weekly' and days_since_last >= 7:
                    should_send = True
                elif subscription.frequency == 'biweekly' and days_since_last >= 14:
                    should_send = True
                elif subscription.frequency == 'monthly' and days_since_last >= 30:
                    should_send = True
            
            if not should_send and not dry_run:
                skipped_count += 1
                logger.debug(f"Skipping {subscription.user.email} - last sent {days_since_last} days ago (frequency: {subscription.frequency})")
                continue
            
            if dry_run:
                logger.info(f"[DRY RUN] Would send newsletter to {subscription.user.email} (frequency: {subscription.frequency})")
                sent_count += 1
            else:
                # Get user-specific preferences and regenerate content
                if subscription.preferences:
                    newsletter_content = generator.generate_newsletter_content(user=subscription.user)
                else:
                    newsletter_content = base_content
                
                success = send_newsletter_email(subscription.user, newsletter_content)
                
                if success:
                    sent_count += 1
                    # Update last_sent timestamp
                    subscription.last_sent = now
                    subscription.save(update_fields=['last_sent'])
                    logger.info(f"Newsletter sent to {subscription.user.email} (frequency: {subscription.frequency})")
                else:
                    failed_count += 1
        
        logger.info(f"Newsletter sending complete: {sent_count} sent, {failed_count} failed, {skipped_count} skipped")
        return sent_count
        
    except Exception as e:
        logger.error(f"Error in send_newsletter_to_subscribers: {e}")
        return 0
