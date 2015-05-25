# -*- coding: utf-8 -*-
"""
    payment.py

    :copyright: (c) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from decimal import Decimal

from trytond.model import ModelSQL, ModelView, fields
from trytond.pyson import Eval, Not
from trytond.pool import Pool

__all__ = ['SalePayment']


class SalePayment(ModelSQL, ModelView):
    "Sale Payment"
    __name__ = 'sale.payment'

    sequence = fields.Integer('Sequence', required=True)
    sale = fields.Many2One('sale.sale', 'Sale', select=True, required=True)
    party = fields.Function(
        fields.Many2One('party.party', 'Party'),
        'on_change_with_party'
    )
    currency_digits = fields.Function(
        fields.Integer('Currency Digits'),
        'on_change_with_currency_digits'
    )
    gateway = fields.Many2One(
        'payment_gateway.gateway', 'Gateway', required=True,
        ondelete='RESTRICT',
    )
    provider = fields.Function(
        fields.Char('Provider'), 'get_provider'
    )
    method = fields.Function(
        fields.Char('Payment Gateway Method'), 'get_method'
    )
    payment_profile = fields.Many2One(
        'party.payment_profile', 'Payment Profile',
        domain=[
            ('party', '=', Eval('party')),
            ('gateway', '=', Eval('gateway')),
        ],
        states={
            'required': Eval('method') == 'credit_card'
        },
        ondelete='RESTRICT', depends=['party', 'gateway', 'method'],
    )
    amount = fields.Numeric(
        'Amount', digits=(16, Eval('currency_digits', 2)),
        required=True, depends=['currency_digits'],
    )
    amount_consumed = fields.Function(
        fields.Numeric(
            'Amount Consumed', digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
        ), 'get_amount_consumed'
    )
    amount_remaining = fields.Function(
        fields.Numeric(
            'Amount Remaining', digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
        ), 'get_amount_remaining'
    )
    payment_transactions = fields.One2Many(
        'payment_gateway.transaction', 'payment', 'Payment Transactions',
    )
    reference = fields.Char(
        'Reference', states={
            'invisible': Not(Eval('method') == 'manual'),
        }
    )

    @staticmethod
    def default_sequence():
        return 10

    @fields.depends('sale')
    def on_change_with_currency_digits(self, name=None):
        if self.sale.currency:
            return self.sale.currency.digits
        return 2

    @fields.depends('sale')
    def on_change_with_party(self, name=None):
        return self.sale.party.id

    def get_provider(self, name=None):
        """
        Return the gateway provider based on the gateway
        """
        return self.gateway.provider

    def get_method(self, name=None):
        """
        Return the method based on the gateway
        """
        return self.gateway.method

    def get_amount_consumed(self, name):
        """
        Return the actual amount blocked in authorized transactions, or
        captured
        """
        PaymentTransaction = Pool().get('payment_gateway.transaction')

        payment_transactions = PaymentTransaction.search([
            ('payment', '=', self)
        ])
        amount_consumed = Decimal('0')
        for transaction in payment_transactions:
            if transaction.state not in ('authorized', 'completed', 'posted'):
                continue    # pragma: no cover
            amount_consumed += transaction.amount
        return amount_consumed

    def get_amount_remaining(self, name):
        """
        Return the amount remaining based on transactions.
        This will never return a negative amount, even if overdrawn.
        """
        return max(self.amount - self.amount_consumed, Decimal('0'))

    @classmethod
    def cancel(cls, payments):
        """
        Cancel all payment transactions related to payment
        """
        PaymentTransaction = Pool().get('payment_gateway.transaction')

        payment_transactions = []
        for payment in payments:
            payment_transactions.extend(payment.payment_transactions)

        PaymentTransaction.cancel(payment_transactions)

    def authorize(self, amount, description):
        """
        Authorize the given amount from this transaction
        """
        PaymentTransaction = Pool().get('payment_gateway.transaction')
        Date = Pool().get('ir.date')

        if amount > self.amount_remaining:
            self.raise_user_error(
                'Insufficient amount remaining in payment\n'
                'Amount to capture: %s\n'
                'Amount authorized: %s\n'
                'Amount remaining: %s\n'
                'Transactions: %s' % (
                    amount,
                    self.amount,
                    self.amount_remaining,
                    len(self.payment_transactions),
                )
            )

        if self.method == 'credit_card' and self.sale.last_card_payment != self:
            amount = min(amount, self.amount_remaining)

        transaction, = PaymentTransaction.create([{
            'description': description or 'Auto charge from payment',
            # 'origin': self,
            'date': Date.today(),
            'party': self.sale.party,
            'payment_profile': self.payment_profile,
            'address': (
                self.payment_profile and
                self.payment_profile.address or self.sale.invoice_address),
            'amount': self.sale.currency.round(amount),
            'currency': self.sale.currency,
            'gateway': self.gateway,
            'sale': self.sale.id,
            'payment': self.id,
            'provider_reference': self.reference,
        }])
        PaymentTransaction.authorize([transaction])
        return transaction

    @classmethod
    def delete(cls, payments):
        """
        Delete a payment only if there is no amount consumed
        """
        for payment in payments:
            if payment.amount_consumed:
                cls.raise_user_error(
                    "This Payment cannot be deleted as some amount has " +
                    "already been consumed."
                )
        super(SalePayment, cls).delete(payments)
