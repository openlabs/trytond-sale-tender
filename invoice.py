# -*- coding: utf-8 -*-
"""
    invoice.py

    :copyright: (c) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from trytond.pool import PoolMeta, Pool

__metaclass__ = PoolMeta
__all__ = ['Invoice']


class Invoice:
    __name__ = 'account.invoice'

    def auto_pay_from(self, sale):
        """
        Automatically try to pay the invoice from given sale.
        If there are open authorizations, use them, if not start a new charge.
        """
        PaymentTransaction = Pool().get('payment_gateway.transaction')

        amount = self.amount_to_pay_today

        method_order = ['manual', 'credit_card']
        authorized_transactions = sorted(
            [t for t in sale.gateway_transactions if t.state == 'authorized'],
            key=lambda t: method_order.index(t.method)
        )

        txns_to_settle = []
        for transaction in authorized_transactions:
            if not amount:
                break       # pragma: no cover

            capture_amount = min(amount, transaction.amount)

            # Write the new amount of the transaction as the amount
            # required to be captured
            transaction.amount = capture_amount
            transaction.save()
            txns_to_settle.append(transaction)

            amount -= capture_amount

        if amount:      # pragma: no cover
            # Amount is still left to capture, capture directly from an
            # available sale payment
            #
            # TODO: add this part also to coverage
            new_transactions = sale.authorize_from_sale_payments(
                amount, 'Invoice: %s' % self.number
            )

            for transaction in new_transactions:
                if not amount:
                    break

                # Raise UserError if the transaction failed to authorize
                if transaction.state == 'failed':
                    # Cancel all the authorized transactions as UserError will
                    # roll them back
                    txns_to_cancel = filter(
                        lambda t: t.state == 'authorized',
                        new_transactions
                    )
                    PaymentTransaction.cancel(txns_to_cancel)

                    self.raise_user_error(
                        'Process cannot be completed due to payment failure.'
                    )

                capture_amount = min(amount, transaction.amount)

                # Write the new amount of the transaction as the amount
                # required to be captured
                transaction.amount = capture_amount
                transaction.save()
                txns_to_settle.append(transaction)

                amount -= capture_amount

        PaymentTransaction.settle(txns_to_settle)

        for transaction in txns_to_settle:
            self.pay_using_transaction(transaction)
