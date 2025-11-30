"""
Management command to test Transaction model
Usage: python manage.py test_transaction
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings


class Command(BaseCommand):
    help = 'Test if Transaction model and table exist'

    def handle(self, *args, **options):
        self.stdout.write("Testing Transaction model...")
        
        # Test 1: Check if model can be imported
        try:
            from portfolio.models import Transaction
            self.stdout.write(self.style.SUCCESS("✓ Transaction model imported successfully"))
        except ImportError as e:
            self.stdout.write(self.style.ERROR(f"✗ Failed to import Transaction model: {e}"))
            return
        
        # Test 2: Check if table exists
        table_name = Transaction._meta.db_table
        self.stdout.write(f"Checking table: {table_name}")
        
        with connection.cursor() as cursor:
            if connection.vendor == 'postgresql':
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = %s
                    );
                """, [table_name])
                exists = cursor.fetchone()[0]
            elif connection.vendor == 'sqlite':
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name=?;
                """, [table_name])
                exists = cursor.fetchone() is not None
            else:
                self.stdout.write(self.style.WARNING(f"Unknown database vendor: {connection.vendor}"))
                exists = False
        
        if exists:
            self.stdout.write(self.style.SUCCESS(f"✓ Table '{table_name}' exists"))
        else:
            self.stdout.write(self.style.ERROR(f"✗ Table '{table_name}' does NOT exist"))
            self.stdout.write(self.style.WARNING("Run: python manage.py migrate"))
            return
        
        # Test 3: Try to query the model
        try:
            count = Transaction.objects.count()
            self.stdout.write(self.style.SUCCESS(f"✓ Can query Transaction model (count: {count})"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Cannot query Transaction model: {e}"))
            return
        
        # Test 4: Check TransactionService
        try:
            from portfolio.services import TransactionService
            self.stdout.write(self.style.SUCCESS("✓ TransactionService imported successfully"))
        except ImportError as e:
            self.stdout.write(self.style.ERROR(f"✗ Failed to import TransactionService: {e}"))
        
        self.stdout.write(self.style.SUCCESS("\nAll tests passed! Transaction feature should work."))



