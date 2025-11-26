"""
Management command to add Royal Bank of Canada (RY) as sponsored stock
Usage: python manage.py add_royal_bank_sponsored
"""
from django.core.management.base import BaseCommand
from portfolio.models import SponsoredContent, Stock


class Command(BaseCommand):
    help = 'Add Royal Bank of Canada (RY) as a sponsored/featured stock'

    def handle(self, *args, **options):
        # Find Royal Bank stock
        try:
            ry_stock = Stock.objects.get(symbol='RY')
        except Stock.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                'Royal Bank of Canada (RY) stock not found in database. '
                'Please add the stock first or use a different symbol.'
            ))
            return
        
        # Check if sponsored content for RY already exists
        existing = SponsoredContent.objects.filter(
            stock=ry_stock,
            content_type='featured_stock'
        ).first()
        
        if existing:
            self.stdout.write(self.style.WARNING(
                f'Sponsored content for RY already exists (ID: {existing.id})'
            ))
            # Update the existing one
            existing.title = 'Featured Dividend Stock: Royal Bank of Canada (RY)'
            existing.description = (
                'Royal Bank of Canada is one of Canada\'s largest banks with a strong dividend history. '
                'Currently offering a competitive dividend yield with consistent quarterly payments. '
                'Perfect for long-term dividend investors seeking stability and growth.'
            )
            existing.is_active = True
            existing.display_order = 1
            existing.save()
            self.stdout.write(self.style.SUCCESS(
                f'Updated existing sponsored content for RY'
            ))
        else:
            # Create new sponsored content
            sponsored = SponsoredContent.objects.create(
                title='Featured Dividend Stock: Royal Bank of Canada (RY)',
                content_type='featured_stock',
                description=(
                    'Royal Bank of Canada is one of Canada\'s largest banks with a strong dividend history. '
                    'Currently offering a competitive dividend yield with consistent quarterly payments. '
                    'Perfect for long-term dividend investors seeking stability and growth.'
                ),
                stock=ry_stock,
                is_active=True,
                display_order=1,
            )
            self.stdout.write(self.style.SUCCESS(
                f'Successfully created sponsored content for Royal Bank of Canada (RY) (ID: {sponsored.id})'
            ))
            self.stdout.write(f'  Title: {sponsored.title}')
            self.stdout.write(f'  Stock: {sponsored.stock.symbol} - {sponsored.stock.company_name}')
            self.stdout.write(f'  Active: {sponsored.is_active}')
            self.stdout.write(f'  Display Order: {sponsored.display_order}')
            self.stdout.write(self.style.SUCCESS(
                '\nThe sponsored stock will now appear on:'
            ))
            self.stdout.write('  - Home page (before dividend stocks)')
            self.stdout.write('  - All Stocks page (before stocks grid)')
            self.stdout.write('  - Dashboard (at the bottom)')

