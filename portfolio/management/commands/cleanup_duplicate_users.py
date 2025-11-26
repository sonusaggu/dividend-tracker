"""
Django management command to find and clean up duplicate users with same email
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Count
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Find and optionally delete duplicate users with the same email address'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show duplicates without deleting (default)',
        )
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Actually delete duplicate users (keeps the oldest user)',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Clean up duplicates for a specific email address',
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        delete = options['delete']
        specific_email = options.get('email')
        
        self.stdout.write("=" * 70)
        self.stdout.write("Duplicate User Cleanup")
        self.stdout.write("=" * 70)
        
        if not delete and not dry_run:
            self.stdout.write(self.style.WARNING("\n⚠️  Running in DRY-RUN mode (no changes will be made)"))
            self.stdout.write("   Use --delete to actually delete duplicates")
            self.stdout.write("   Use --dry-run to explicitly show what would be deleted\n")
        
        # Find duplicate emails
        if specific_email:
            duplicates = User.objects.filter(email=specific_email).order_by('date_joined')
            if duplicates.count() <= 1:
                self.stdout.write(self.style.SUCCESS(f"\n✓ No duplicates found for email: {specific_email}"))
                return
            email_groups = {specific_email: list(duplicates)}
        else:
            # Find all emails that appear more than once
            duplicate_emails = User.objects.values('email')\
                .annotate(count=Count('email'))\
                .filter(count__gt=1, email__isnull=False)\
                .exclude(email='')\
                .values_list('email', flat=True)
            
            if not duplicate_emails:
                self.stdout.write(self.style.SUCCESS("\n✓ No duplicate emails found!"))
                return
            
            # Group users by email
            email_groups = {}
            for email in duplicate_emails:
                users = User.objects.filter(email=email).order_by('date_joined')
                email_groups[email] = list(users)
        
        # Display duplicates
        total_duplicates = 0
        users_to_delete = []
        
        self.stdout.write(f"\n📊 Found {len(email_groups)} email(s) with duplicates:\n")
        
        for email, users in email_groups.items():
            count = len(users)
            total_duplicates += (count - 1)  # All except the first one
            
            self.stdout.write(f"\n📧 Email: {email}")
            self.stdout.write(f"   Total users: {count}")
            
            # Keep the oldest user (first by date_joined)
            keep_user = users[0]
            delete_users = users[1:]
            
            self.stdout.write(f"\n   ✓ KEEP: {keep_user.username} (ID: {keep_user.id}, Joined: {keep_user.date_joined})")
            
            for user in delete_users:
                self.stdout.write(f"   ✗ DELETE: {user.username} (ID: {user.id}, Joined: {user.date_joined})")
                users_to_delete.append(user)
        
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(f"Summary: {total_duplicates} duplicate user(s) found")
        self.stdout.write("=" * 70)
        
        if delete:
            self.stdout.write(self.style.WARNING("\n⚠️  DELETING DUPLICATES..."))
            deleted_count = 0
            
            for user in users_to_delete:
                try:
                    username = user.username
                    user_id = user.id
                    user.delete()
                    deleted_count += 1
                    self.stdout.write(self.style.SUCCESS(f"   ✓ Deleted user: {username} (ID: {user_id})"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"   ✗ Error deleting user {user.username}: {e}"))
            
            self.stdout.write(self.style.SUCCESS(f"\n✅ Successfully deleted {deleted_count} duplicate user(s)"))
        else:
            self.stdout.write(self.style.WARNING(f"\n⚠️  DRY RUN: {total_duplicates} user(s) would be deleted"))
            self.stdout.write("   Run with --delete to actually delete them")
        
        self.stdout.write("\n" + "=" * 70)

