# -*- coding: utf-8 -*-
"""
    sale.py

    :copyright: (c) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from decimal import Decimal

from trytond.model import ModelView, Workflow, fields
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval, Bool, And, Or, Not
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateView, StateTransition, Button

from trytond.modules.payment_gateway.transaction import BaseCreditCardViewMixin

__metaclass__ = PoolMeta
__all__ = ['Sale', 'AddSalePaymentView', 'AddSalePayment']


class Sale:
    __name__ = 'sale.sale'

    payments = fields.One2Many(
        'sale.payment', 'sale', 'Payments', readonly=True
    )
    payment_total = fields.Function(
        fields.Numeric(
            'Total Payment', digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
            help="Total value of payments to capture later."
        ), 'get_payment_amounts',
    )
    payment_remaining = fields.Function(
        fields.Numeric(
            'Payment Remaining', digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
            help="Total value of payments remaining."
        ), 'get_payment_amounts',
    )
    amount_invoiced = fields.Function(
        fields.Numeric(
            'Amount Invoices', digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
            help="Total value of invoices raised"
        ), 'get_payment_amounts',
    )
    payment_authorized = fields.Function(
        fields.Numeric(
            'Payment Authorized', digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
            help="Amount authorized to be captured."
        ), 'get_payment',
    )
    payment_captured = fields.Function(
        fields.Numeric(
            'Payment Captured', digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits'],
            help="Amount already captured by LN"
        ), 'get_payment',
    )
    last_card_payment = fields.Function(
        fields.Many2One('sale.payment', 'Last Card Payment'),
        'get_last_card_payment'
    )

    @classmethod
    def __setup__(cls):
        super(Sale, cls).__setup__()
        cls._buttons.update({
            'add_payment': {
                'invisible': Eval('state').in_(['cancel', 'draft']),
            },
        })

    def get_last_card_payment(self, name=None):
        """
        Returns the last card in the payments
        """
        for payment in self.payments[::-1]:
            if payment.method == 'credit_card':
                return payment.id

    def get_payment_amounts(self, name):
        """Return amount from payments.
        """
        Payment = Pool().get('sale.payment')

        payments = Payment.search([('sale', '=', self.id)])
        # TODO: Handle currency
        if name == 'payment_total':
            return sum([payment.amount for payment in payments])
        elif name == 'payment_remaining':
            return sum([payment.amount_remaining for payment in payments])
        elif name == 'amount_invoiced':
            # TODO: It is possible that the invoices raised from here
            # could be from multiple sales. So this information needs to
            # be fetched ideally from lines. But invoice line amounts do
            # not include tax.
            return sum([invoice.total_amount for invoice in self.invoices])

    def get_payment(self, name):
        """
        Ensure that the amount to receive does not ignore the sale payments
        """
        if name == 'payment_captured':
            # Captured payment includes manual payments which are
            # considered received the moment they are processed and the
            # credit card transactions which are captured.
            sum_transactions = lambda txns: sum((txn.amount for txn in txns))
            transactions = filter(
                lambda txn: txn.state in ('completed', 'posted'),
                self.gateway_transactions
            )
            return Decimal(sum_transactions(transactions))

        elif name == 'payment_authorized':
            sum_transactions = lambda txns: sum((txn.amount for txn in txns))
            transactions = filter(
                lambda txn: txn.state == 'authorized',
                self.gateway_transactions
            )
            return Decimal(sum_transactions(transactions))
        # Also the getter for payment fields defined in sale payment
        # gateway
        return super(Sale, self).get_payment(name)

    @classmethod
    @ModelView.button_action('sale_payment.wizard_add_payment')
    def add_payment(cls, sales):
        pass

    def authorize_from_sale_payments(self, amount, description):
        """
        Authorize the given amount from available sale payments

        :param amount: Decimal amount in sale currency to capture.
        :param description: Description for the payment transaction.
        """
        if amount > self.payment_remaining:
            self.raise_user_error(
                'Insufficient amount remaining in sale payments\n'
                'Amount to capture: %s\n'
                'Amount authorized: %s\n'
                'Amount remaining: %s\n'
                'Payments: %s' % (
                    amount,
                    self.payment_total,
                    self.payment_remaining,
                    len(self.payments),
                )
            )

        transactions = []
        order = ['manual', 'credit_card']
        sorted_payments = sorted(
            self.payments,
            key=lambda t: order.index(t.method)
        )
        for payment in sorted_payments:

            if not amount:
                break

            if not payment.amount_remaining:
                continue

            # The amount to capture is the amount_remaining if the
            # amount_remaining is less than the amount we seek.
            capture_amount = min(amount, payment.amount_remaining)
            transactions.append(
                payment.authorize(capture_amount, description)
            )
            amount -= capture_amount

        return transactions

    def create_invoice(self, invoice_type):
        """Pay invoice from payments available.
        """
        Invoice = Pool().get('account.invoice')

        invoice = super(Sale, self).create_invoice(invoice_type)

        if not invoice:
            return invoice

        if invoice_type == 'out_invoice':
            # Pay invoices with any authorized options first.
            # If there are no authorized options, then go ahead and
            # capture.
            invoice.auto_pay_from(self)

            invoice = Invoice(invoice.id)   # Reload record
            if invoice.amount_to_pay_today:
                # If still there is amount remaining. Flag the order and
                # send a notification
                #
                # TODO: Send email to new user group about the invoice
                # which is still unpaid
                pass    # pragma: no cover

        return invoice

    @classmethod
    @Workflow.transition('processing')
    def proceed(cls, sales):
        super(Sale, cls).proceed(sales)

        for sale in sales:
            sale.authorize_from_sale_payments(
                sale.total_amount, "Processing Sale"
            )


class AddSalePaymentView(BaseCreditCardViewMixin, ModelView):
    """
    View for adding Sale Payments
    """
    __name__ = 'sale.payment.add_view'

    sale = fields.Many2One(
        'sale.sale', 'Sale', required=True, readonly=True
    )

    party = fields.Many2One('party.party', 'Party', readonly=True)
    gateway = fields.Many2One(
        'payment_gateway.gateway', 'Gateway', required=True,
    )
    currency_digits = fields.Function(
        fields.Integer('Currency Digits'),
        'get_currency_digits'
    )
    method = fields.Function(
        fields.Char('Payment Gateway Method'), 'get_method'
    )
    use_existing_card = fields.Boolean(
        'Use existing Card?', states={
            'invisible': Eval('method') != 'credit_card'
        }, depends=['method']
    )
    payment_profile = fields.Many2One(
        'party.payment_profile', 'Payment Profile',
        domain=[
            ('party', '=', Eval('party')),
            ('gateway', '=', Eval('gateway')),
        ],
        states={
            'required': And(
                Eval('method') == 'credit_card', Bool(Eval('use_existing_card'))
            ),
            'invisible': ~Bool(Eval('use_existing_card'))
        }, depends=['method', 'use_existing_card', 'party', 'gateway']
    )
    amount = fields.Numeric(
        'Amount', digits=(16, Eval('currency_digits', 2)),
        required=True, depends=['currency_digits'],
    )
    reference = fields.Char(
        'Reference', states={
            'invisible': Not(Eval('method') == 'manual'),
        }
    )

    @classmethod
    def __setup__(cls):
        super(AddSalePaymentView, cls).__setup__()

        INV = Or(
            Eval('method') == 'manual',
            And(
                Eval('method') == 'credit_card',
                Bool(Eval('use_existing_card'))
            )
        )
        STATE1 = {
            'required': And(
                ~Bool(Eval('use_existing_card')),
                Eval('method') == 'credit_card'
            ),
            'invisible': INV
        }
        DEPENDS = ['use_existing_card', 'method']

        cls.owner.states.update(STATE1)
        cls.owner.depends.extend(DEPENDS)
        cls.number.states.update(STATE1)
        cls.number.depends.extend(DEPENDS)
        cls.expiry_month.states.update(STATE1)
        cls.expiry_month.depends.extend(DEPENDS)
        cls.expiry_year.states.update(STATE1)
        cls.expiry_year.depends.extend(DEPENDS)
        cls.csc.states.update(STATE1)
        cls.csc.depends.extend(DEPENDS)
        cls.swipe_data.states = {'invisible': INV}
        cls.swipe_data.depends = ['method']

    def get_currency_digits(self, name):
        return self.sale.currency_digits if self.sale else 2

    def get_method(self, name=None):
        """
        Return the method based on the gateway
        """
        return self.gateway.method

    @fields.depends('gateway')
    def on_change_gateway(self):
        if self.gateway:
            return {
                'method': self.gateway.method,
            }
        return {}


class AddSalePayment(Wizard):
    """
    Wizard to add a Sale Payment
    """
    __name__ = 'sale.payment.add'

    start_state = 'payment_info'

    payment_info = StateView(
        'sale.payment.add_view',
        'sale_payment.sale_payment_add_view_form',
        [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Pay', 'pay', 'tryton-ok', default=True)
        ]
    )
    pay = StateTransition()

    def default_payment_info(self, fields=None):
        Sale = Pool().get('sale.sale')

        sale = Sale(Transaction().context.get('active_id'))

        res = {
            'sale': sale.id,
            'party': sale.party.id,
            'owner': sale.party.name,
            'currency_digits': sale.currency_digits,
            'amount': sale.amount_to_receive - sale.payment_total,
        }
        return res

    def create_sale_payment(self, profile=None):
        """
        Helper function to create new payment
        """
        SalePayment = Pool().get('sale.payment')

        SalePayment.create([{
            'sale': Transaction().context.get('active_id'),
            'party': self.payment_info.party,
            'gateway': self.payment_info.gateway,
            'payment_profile': profile,
            'amount': self.payment_info.amount,
            'reference': self.payment_info.reference or None,
        }])

    def create_payment_profile(self):
        """
        Helper function to create payment profile
        """
        Sale = Pool().get('sale.sale')
        ProfileWizard = Pool().get(
            'party.party.payment_profile.add', type="wizard"
        )
        profile_wizard = ProfileWizard(
            ProfileWizard.create()[0]
        )
        profile_wizard.card_info.owner = self.payment_info.owner
        profile_wizard.card_info.number = self.payment_info.number
        profile_wizard.card_info.expiry_month = self.payment_info.expiry_month
        profile_wizard.card_info.expiry_year = self.payment_info.expiry_year
        profile_wizard.card_info.csc = self.payment_info.csc or ''
        profile_wizard.card_info.gateway = self.payment_info.gateway
        profile_wizard.card_info.provider = self.payment_info.gateway.provider
        profile_wizard.card_info.address = Sale(
            Transaction().context.get('active_id')
        ).invoice_address
        profile_wizard.card_info.party = self.payment_info.party

        with Transaction().set_context(return_profile=True):
            profile = profile_wizard.transition_add()
        return profile

    def transition_pay(self):
        """
        Creates a new payment and ends the wizard
        """
        profile = self.payment_info.payment_profile
        if self.payment_info.method == 'credit_card' and (
            not self.payment_info.use_existing_card
        ):
            profile = self.create_payment_profile()

        self.create_sale_payment(profile=profile)
        return 'end'
