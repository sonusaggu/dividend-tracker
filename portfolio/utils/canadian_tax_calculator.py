"""
Canadian Tax Calculator for Stock Investors
Calculates dividend tax credits, capital gains, and RRSP/TFSA benefits
"""
from decimal import Decimal
from datetime import date
import logging

logger = logging.getLogger(__name__)


class CanadianTaxCalculator:
    """Calculator for Canadian tax-related calculations"""
    
    # 2024 Federal Tax Rates (marginal rates)
    FEDERAL_TAX_BRACKETS = {
        55867: 0.15,   # 15% on first $55,867
        111733: 0.205, # 20.5% on next $55,866
        173205: 0.26,  # 26% on next $61,472
        246752: 0.29,  # 29% on next $73,547
        float('inf'): 0.33  # 33% on remaining
    }
    
    # 2024 Federal Dividend Tax Credit Rate
    DIVIDEND_TAX_CREDIT_RATE = 0.15  # 15% federal credit
    
    # Gross-up factor for eligible dividends (2024)
    DIVIDEND_GROSS_UP = 1.38  # 38% gross-up for eligible dividends
    
    # Capital Gains Inclusion Rate
    CAPITAL_GAINS_RATE = 0.50  # 50% of capital gains are taxable
    
    @staticmethod
    def calculate_dividend_tax_credit(dividend_amount, is_eligible=True, province='ON'):
        """
        Calculate dividend tax credit for Canadian investors
        
        Args:
            dividend_amount: Annual dividend amount in CAD
            is_eligible: Whether dividend is eligible (most TSX dividends are)
            province: Province code (ON, BC, AB, QC, etc.)
        
        Returns:
            dict with tax calculations
        """
        try:
            dividend_amount = float(dividend_amount)
            
            if is_eligible:
                # Gross-up the dividend
                grossed_up_dividend = dividend_amount * CanadianTaxCalculator.DIVIDEND_GROSS_UP
                
                # Federal tax credit (15% of grossed-up amount)
                federal_credit = grossed_up_dividend * CanadianTaxCalculator.DIVIDEND_TAX_CREDIT_RATE
                
                # Provincial credit (varies by province, using ON as default)
                provincial_credit_rate = CanadianTaxCalculator._get_provincial_credit_rate(province)
                provincial_credit = grossed_up_dividend * provincial_credit_rate
                
                total_credit = federal_credit + provincial_credit
                
                # Effective tax rate (approximate)
                # Most Canadians pay little to no tax on eligible dividends
                effective_tax_rate = max(0, (grossed_up_dividend * 0.20 - total_credit) / dividend_amount)
                
                return {
                    'dividend_amount': dividend_amount,
                    'grossed_up_amount': round(grossed_up_dividend, 2),
                    'federal_credit': round(federal_credit, 2),
                    'provincial_credit': round(provincial_credit, 2),
                    'total_credit': round(total_credit, 2),
                    'effective_tax_rate': round(effective_tax_rate * 100, 2),
                    'after_tax_amount': round(dividend_amount * (1 - effective_tax_rate), 2),
                    'is_eligible': is_eligible,
                    'province': province
                }
            else:
                # Non-eligible dividends (less common)
                grossed_up_dividend = dividend_amount * 1.15  # 15% gross-up
                federal_credit = grossed_up_dividend * 0.09  # 9% credit
                provincial_credit = grossed_up_dividend * 0.04  # Approximate
                
                return {
                    'dividend_amount': dividend_amount,
                    'grossed_up_amount': round(grossed_up_dividend, 2),
                    'federal_credit': round(federal_credit, 2),
                    'provincial_credit': round(provincial_credit, 2),
                    'total_credit': round(federal_credit + provincial_credit, 2),
                    'effective_tax_rate': 0.0,  # Simplified
                    'after_tax_amount': dividend_amount,
                    'is_eligible': False,
                    'province': province
                }
        except Exception as e:
            logger.error(f"Error calculating dividend tax credit: {e}")
            return None
    
    @staticmethod
    def _get_provincial_credit_rate(province):
        """Get provincial dividend tax credit rate"""
        rates = {
            'ON': 0.10,  # Ontario: 10%
            'BC': 0.12,  # British Columbia: 12%
            'AB': 0.10,  # Alberta: 10%
            'QC': 0.115, # Quebec: 11.5%
            'MB': 0.11,  # Manitoba: 11%
            'SK': 0.11,  # Saskatchewan: 11%
            'NS': 0.08,  # Nova Scotia: 8%
            'NB': 0.10,  # New Brunswick: 10%
            'NL': 0.08,  # Newfoundland: 8%
            'PE': 0.10,  # Prince Edward Island: 10%
            'NT': 0.11,  # Northwest Territories: 11%
            'YT': 0.12,  # Yukon: 12%
            'NU': 0.11,  # Nunavut: 11%
        }
        return rates.get(province.upper(), 0.10)  # Default to ON rate
    
    @staticmethod
    def calculate_capital_gains_tax(capital_gain, taxable_income, province='ON'):
        """
        Calculate capital gains tax
        
        Args:
            capital_gain: Capital gain amount
            taxable_income: Total taxable income (before capital gains)
            province: Province code
        
        Returns:
            dict with tax calculations
        """
        try:
            capital_gain = float(capital_gain)
            taxable_income = float(taxable_income)
            
            # Only 50% of capital gains are taxable
            taxable_capital_gain = capital_gain * CanadianTaxCalculator.CAPITAL_GAINS_RATE
            
            # Total taxable income including capital gains
            total_taxable = taxable_income + taxable_capital_gain
            
            # Calculate tax (simplified - uses average rate)
            # In reality, this would use marginal rates
            estimated_tax_rate = CanadianTaxCalculator._estimate_tax_rate(total_taxable, province)
            
            # Tax on capital gain portion
            tax_on_gain = taxable_capital_gain * estimated_tax_rate
            
            # Effective rate on capital gain
            effective_rate = (tax_on_gain / capital_gain) * 100 if capital_gain > 0 else 0
            
            return {
                'capital_gain': capital_gain,
                'taxable_portion': round(taxable_capital_gain, 2),
                'estimated_tax_rate': round(estimated_tax_rate * 100, 2),
                'tax_payable': round(tax_on_gain, 2),
                'after_tax_gain': round(capital_gain - tax_on_gain, 2),
                'effective_rate': round(effective_rate, 2),
                'province': province
            }
        except Exception as e:
            logger.error(f"Error calculating capital gains tax: {e}")
            return None
    
    @staticmethod
    def _estimate_tax_rate(taxable_income, province='ON'):
        """Estimate combined federal+provincial tax rate"""
        # Simplified average rate calculation
        # In production, this would use actual tax brackets
        
        if taxable_income <= 55867:
            base_rate = 0.15
        elif taxable_income <= 111733:
            base_rate = 0.205
        elif taxable_income <= 173205:
            base_rate = 0.26
        elif taxable_income <= 246752:
            base_rate = 0.29
        else:
            base_rate = 0.33
        
        # Add provincial rate (approximate)
        provincial_rates = {
            'ON': 0.10, 'BC': 0.12, 'AB': 0.10, 'QC': 0.15,
            'MB': 0.12, 'SK': 0.11, 'NS': 0.15, 'NB': 0.14,
            'NL': 0.13, 'PE': 0.10
        }
        provincial_rate = provincial_rates.get(province.upper(), 0.10)
        
        return base_rate + provincial_rate
    
    @staticmethod
    def calculate_rrsp_contribution_limit(age, previous_year_income, unused_room=0):
        """
        Calculate RRSP contribution limit
        
        Args:
            age: Current age
            previous_year_income: Previous year's earned income
            unused_room: Unused contribution room from previous years
        
        Returns:
            dict with RRSP calculations
        """
        try:
            # 2024 RRSP contribution limit is 18% of previous year's income
            # Maximum limit for 2024: $31,560
            max_limit_2024 = 31560
            
            # Calculate based on income
            contribution_limit = min(previous_year_income * 0.18, max_limit_2024)
            
            # Add unused room
            total_room = contribution_limit + unused_room
            
            # Tax savings estimate (depends on marginal rate)
            estimated_savings = contribution_limit * 0.30  # Assume 30% marginal rate
            
            return {
                'contribution_limit': round(contribution_limit, 2),
                'unused_room': unused_room,
                'total_available_room': round(total_room, 2),
                'max_limit_2024': max_limit_2024,
                'estimated_tax_savings': round(estimated_savings, 2),
                'age': age
            }
        except Exception as e:
            logger.error(f"Error calculating RRSP limit: {e}")
            return None
    
    @staticmethod
    def calculate_tfsa_contribution_limit(age, year=2024, previous_contributions=0):
        """
        Calculate TFSA contribution limit
        
        Args:
            age: Current age (must be 18+)
            year: Tax year
            previous_contributions: Total previous contributions
        
        Returns:
            dict with TFSA calculations
        """
        try:
            if age < 18:
                return {
                    'eligible': False,
                    'message': 'Must be 18 or older to contribute to TFSA'
                }
            
            # TFSA limits by year (cumulative)
            tfsa_limits = {
                2009: 5000, 2010: 5000, 2011: 5000, 2012: 5000, 2013: 5500,
                2014: 5500, 2015: 10000, 2016: 5500, 2017: 5500, 2018: 5500,
                2019: 6000, 2020: 6000, 2021: 6000, 2022: 6000, 2023: 6500,
                2024: 7000, 2025: 7000  # Estimated
            }
            
            # Calculate cumulative limit from 2009 to current year
            cumulative_limit = sum(tfsa_limits.get(y, 0) for y in range(2009, year + 1))
            
            # Available room
            available_room = cumulative_limit - previous_contributions
            
            return {
                'eligible': True,
                'year': year,
                'annual_limit': tfsa_limits.get(year, 0),
                'cumulative_limit': cumulative_limit,
                'previous_contributions': previous_contributions,
                'available_room': max(0, round(available_room, 2)),
                'age': age
            }
        except Exception as e:
            logger.error(f"Error calculating TFSA limit: {e}")
            return None
    
    @staticmethod
    def calculate_portfolio_tax_summary(portfolio_data, annual_income, province='ON'):
        """
        Calculate comprehensive tax summary for a portfolio
        
        Args:
            portfolio_data: List of dicts with stock data including:
                - annual_dividends
                - capital_gains
                - shares_owned
            annual_income: Annual taxable income
            province: Province code
        
        Returns:
            dict with comprehensive tax calculations
        """
        try:
            total_dividends = sum(item.get('annual_dividends', 0) for item in portfolio_data)
            total_capital_gains = sum(item.get('capital_gains', 0) for item in portfolio_data)
            
            # Calculate dividend tax
            dividend_tax = CanadianTaxCalculator.calculate_dividend_tax_credit(
                total_dividends, is_eligible=True, province=province
            )
            
            # Calculate capital gains tax
            capital_gains_tax = CanadianTaxCalculator.calculate_capital_gains_tax(
                total_capital_gains, annual_income, province=province
            )
            
            return {
                'total_dividends': round(total_dividends, 2),
                'total_capital_gains': round(total_capital_gains, 2),
                'dividend_tax_info': dividend_tax,
                'capital_gains_tax_info': capital_gains_tax,
                'total_tax_credits': round(
                    (dividend_tax.get('total_credit', 0) if dividend_tax else 0), 2
                ),
                'total_tax_payable': round(
                    (capital_gains_tax.get('tax_payable', 0) if capital_gains_tax else 0), 2
                ),
                'net_after_tax_income': round(
                    total_dividends + total_capital_gains - 
                    (capital_gains_tax.get('tax_payable', 0) if capital_gains_tax else 0), 2
                ),
                'province': province
            }
        except Exception as e:
            logger.error(f"Error calculating portfolio tax summary: {e}")
            return None
