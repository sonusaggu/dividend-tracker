"""
Management command to recalculate gain/loss for all sell transactions
Usage: python manage.py recalculate_gain_loss
"""
from django.core.management.base import BaseCommand
from portfolio.models import Transaction
from portfolio.services import TransactionService
from django.db import transaction as db_transaction


class Command(BaseCommand):
    help = 'Recalculate realized gain/loss for all sell transactions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Recalculate for specific user (username)',
        )
        parser.add_argument(
            '--stock',
            type=str,
            help='Recalculate for specific stock symbol',
        )

    def handle(self, *args, **options):
        username = options.get('user')
        stock_symbol = options.get('stock')
        
        # Get sell transactions
        sell_transactions = Transaction.objects.filter(transaction_type='SELL').select_related('user', 'stock')
        
        if username:
            sell_transactions = sell_transactions.filter(user__username=username)
            self.stdout.write(f"Filtering for user: {username}")
        
        if stock_symbol:
            sell_transactions = sell_transactions.filter(stock__symbol=stock_symbol.upper())
            self.stdout.write(f"Filtering for stock: {stock_symbol.upper()}")
        
        total = sell_transactions.count()
        self.stdout.write(f"Found {total} sell transaction(s) to recalculate...")
        
        if total == 0:
            self.stdout.write(self.style.WARNING("No sell transactions found."))
            return
        
        updated_count = 0
        error_count = 0
        
        for trans in sell_transactions:
            try:
                cost_basis, transactions_used, error = TransactionService.calculate_cost_basis(
                    trans.user, trans.stock, float(trans.shares), trans.cost_basis_method
                )
                
                if error:
                    self.stdout.write(self.style.WARNING(
                        f"  {trans.id}: {trans.user.username} - {trans.stock.symbol} - {error}"
                    ))
                    trans.realized_gain_loss = None
                else:
                    if cost_basis is not None:
                        trans.calculate_realized_gain_loss(cost_basis)
                        self.stdout.write(self.style.SUCCESS(
                            f"  {trans.id}: {trans.user.username} - {trans.stock.symbol} - Gain/Loss: ${trans.realized_gain_loss:.2f}"
                        ))
                    else:
                        trans.realized_gain_loss = None
                        self.stdout.write(self.style.WARNING(
                            f"  {trans.id}: {trans.user.username} - {trans.stock.symbol} - No cost basis calculated"
                        ))
                
                trans.save()
                updated_count += 1
                
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(
                    f"  {trans.id}: Error - {str(e)}"
                ))
        
        self.stdout.write(self.style.SUCCESS(
            f"\nCompleted! Updated: {updated_count}, Errors: {error_count}"
        ))



