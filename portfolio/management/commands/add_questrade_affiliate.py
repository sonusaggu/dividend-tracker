"""
Management command to add Questrade affiliate link
Usage: python manage.py add_questrade_affiliate
"""
from django.core.management.base import BaseCommand
from portfolio.models import AffiliateLink


class Command(BaseCommand):
    help = 'Add Questrade affiliate link to the database'

    def handle(self, *args, **options):
        # Check if Questrade already exists
        existing = AffiliateLink.objects.filter(name__icontains='Questrade').first()
        
        if existing:
            self.stdout.write(self.style.WARNING(
                f'Questrade affiliate already exists: {existing.name} (ID: {existing.id})'
            ))
            # Update the existing one
            existing.affiliate_url = 'https://start.questrade.com/?oaa_promo=656733296488690&s_cid=RAF14_share_link_refer_a_friend_email&utm_medium=share_link&utm_source=refer_a_friend&utm_campaign=RAF14&utm_content=personalized_link'
            existing.is_active = True
            existing.save()
            self.stdout.write(self.style.SUCCESS(
                f'Updated existing Questrade affiliate with new referral link'
            ))
        else:
            # Create new affiliate link
            affiliate = AffiliateLink.objects.create(
                name='Questrade',
                platform_type='broker',
                affiliate_url='https://start.questrade.com/?oaa_promo=656733296488690&s_cid=RAF14_share_link_refer_a_friend_email&utm_medium=share_link&utm_source=refer_a_friend&utm_campaign=RAF14&utm_content=personalized_link',
                description='Low-cost online broker for Canadian investors. Trade stocks, ETFs, options, and more with competitive commissions. Perfect for active traders and long-term investors.',
                logo_url='',  # Can be updated later with actual logo URL
                bonus_offer='Referral bonus available - check current offers',
                is_active=True,
                display_order=2,  # Display after Wealthsimple
            )
            self.stdout.write(self.style.SUCCESS(
                f'Successfully created Questrade affiliate link (ID: {affiliate.id})'
            ))
            self.stdout.write(f'  Name: {affiliate.name}')
            self.stdout.write(f'  URL: {affiliate.affiliate_url}')
            self.stdout.write(f'  Active: {affiliate.is_active}')
            self.stdout.write(f'  Display Order: {affiliate.display_order}')

