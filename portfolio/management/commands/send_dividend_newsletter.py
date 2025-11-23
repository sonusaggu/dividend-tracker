from django.core.management.base import BaseCommand
from portfolio.utils.newsletter_email import send_newsletter_to_subscribers
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Send dividend newsletter to all subscribers'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Test run without actually sending emails',
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write(f"📧 Sending dividend newsletter (dry run: {dry_run})...")
        logger.info(f"📧 Starting newsletter sending (dry_run={dry_run})...")
        
        sent_count = send_newsletter_to_subscribers(dry_run=dry_run)
        
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Dry run complete. Would send {sent_count} newsletters')
            )
            logger.info(f"✅ Dry run complete. Would send {sent_count} newsletters")
        else:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Successfully sent {sent_count} newsletters')
            )
            logger.info(f"✅ Successfully sent {sent_count} newsletters")