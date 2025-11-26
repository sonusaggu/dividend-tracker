"""
Management command to add Wealthsimple affiliate link
Usage: python manage.py add_wealthsimple_affiliate
"""
from django.core.management.base import BaseCommand
from portfolio.models import AffiliateLink


class Command(BaseCommand):
    help = 'Add Wealthsimple affiliate link to the database'

    def handle(self, *args, **options):
        # Check if Wealthsimple already exists
        existing = AffiliateLink.objects.filter(name__icontains='Wealthsimple').first()
        
        if existing:
            self.stdout.write(self.style.WARNING(
                f'Wealthsimple affiliate already exists: {existing.name} (ID: {existing.id})'
            ))
            # Update the existing one
            existing.affiliate_url = 'https://www.wealthsimple.com/invite/RB2R-Q'
            existing.is_active = True
            existing.save()
            self.stdout.write(self.style.SUCCESS(
                f'Updated existing Wealthsimple affiliate with new referral link'
            ))
        else:
            # Create new affiliate link
            affiliate = AffiliateLink.objects.create(
                name='Wealthsimple Trade',
                platform_type='platform',
                affiliate_url='https://www.wealthsimple.com/invite/RB2R-Q',
                description='Commission-free stock trading. Perfect for beginners and experienced investors. Trade stocks, ETFs, and more with zero commission fees.',
                logo_url='',  # Can be updated later with actual logo URL
                bonus_offer='Get $25 when you sign up and deposit $100',
                is_active=True,
                display_order=1,
            )
            self.stdout.write(self.style.SUCCESS(
                f'Successfully created Wealthsimple affiliate link (ID: {affiliate.id})'
            ))
            self.stdout.write(f'  Name: {affiliate.name}')
            self.stdout.write(f'  URL: {affiliate.affiliate_url}')
            self.stdout.write(f'  Active: {affiliate.is_active}')

