# -*- coding: utf-8 -*-
"""
    tests/test_sale.py

    :copyright: (C) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
import os
if 'DB_NAME' not in os.environ:
    from trytond.config import CONFIG
    CONFIG['db_type'] = 'sqlite'
    os.environ['DB_NAME'] = ':memory:'
import unittest
import datetime
from decimal import Decimal
from dateutil.relativedelta import relativedelta

import pycountry

import trytond.tests.test_tryton
from trytond.tests.test_tryton import POOL, USER, DB_NAME, CONTEXT
from trytond.transaction import Transaction
from trytond.exceptions import UserError


class BaseTestCase(unittest.TestCase):
    '''
    Base Test Case sale payment module.
    '''

    def setUp(self):
        """
        Set up data used in the tests.
        this method is called before each test function execution.
        """
        trytond.tests.test_tryton.install_module('sale_payment')

        self.Currency = POOL.get('currency.currency')
        self.Company = POOL.get('company.company')
        self.Party = POOL.get('party.party')
        self.User = POOL.get('res.user')
        self.ProductTemplate = POOL.get('product.template')
        self.Uom = POOL.get('product.uom')
        self.ProductCategory = POOL.get('product.category')
        self.Product = POOL.get('product.product')
        self.Country = POOL.get('country.country')
        self.Subdivision = POOL.get('country.subdivision')
        self.Employee = POOL.get('company.employee')
        self.Journal = POOL.get('account.journal')
        self.PaymentGateway = POOL.get('payment_gateway.gateway')
        self.Sale = POOL.get('sale.sale')
        self.SalePayment = POOL.get('sale.payment')

    def _create_fiscal_year(self, date=None, company=None):
        """
        Creates a fiscal year and requried sequences
        """
        FiscalYear = POOL.get('account.fiscalyear')
        Sequence = POOL.get('ir.sequence')
        SequenceStrict = POOL.get('ir.sequence.strict')
        Company = POOL.get('company.company')

        if date is None:
            date = datetime.date.today()

        if company is None:
            company, = Company.search([], limit=1)

        invoice_sequence, = SequenceStrict.create([{
            'name': '%s' % date.year,
            'code': 'account.invoice',
            'company': company,
        }])
        fiscal_year, = FiscalYear.create([{
            'name': '%s' % date.year,
            'start_date': date + relativedelta(month=1, day=1),
            'end_date': date + relativedelta(month=12, day=31),
            'company': company,
            'post_move_sequence': Sequence.create([{
                'name': '%s' % date.year,
                'code': 'account.move',
                'company': company,
            }])[0],
            'out_invoice_sequence': invoice_sequence,
            'in_invoice_sequence': invoice_sequence,
            'out_credit_note_sequence': invoice_sequence,
            'in_credit_note_sequence': invoice_sequence,
        }])
        FiscalYear.create_period([fiscal_year])
        return fiscal_year

    def _create_coa_minimal(self, company):
        """Create a minimal chart of accounts
        """
        AccountTemplate = POOL.get('account.account.template')
        Account = POOL.get('account.account')

        account_create_chart = POOL.get(
            'account.create_chart', type="wizard")

        account_template, = AccountTemplate.search(
            [('parent', '=', None)]
        )

        session_id, _, _ = account_create_chart.create()
        create_chart = account_create_chart(session_id)
        create_chart.account.account_template = account_template
        create_chart.account.company = company
        create_chart.transition_create_account()

        receivable, = Account.search([
            ('kind', '=', 'receivable'),
            ('company', '=', company),
        ])
        payable, = Account.search([
            ('kind', '=', 'payable'),
            ('company', '=', company),
        ])
        create_chart.properties.company = company
        create_chart.properties.account_receivable = receivable
        create_chart.properties.account_payable = payable
        create_chart.transition_create_properties()

    def _get_account_by_kind(self, kind, company=None, silent=True):
        """Returns an account with given spec
        :param kind: receivable/payable/expense/revenue
        :param silent: dont raise error if account is not found
        """
        Account = POOL.get('account.account')
        Company = POOL.get('company.company')

        if company is None:
            company, = Company.search([], limit=1)

        accounts = Account.search([
            ('kind', '=', kind),
            ('company', '=', company)
        ], limit=1)
        if not accounts and not silent:
            raise Exception("Account not found")
        return accounts[0] if accounts else False

    def _create_payment_term(self):
        """Create a simple payment term with all advance
        """
        PaymentTerm = POOL.get('account.invoice.payment_term')

        return PaymentTerm.create([{
            'name': 'Direct',
            'lines': [('create', [{'type': 'remainder'}])]
        }])

    def _create_countries(self, count=5):
        """
        Create some sample countries and subdivisions
        """
        for country in list(pycountry.countries)[0:count]:
            countries = self.Country.create([{
                'name': country.name,
                'code': country.alpha2,
            }])
            try:
                divisions = pycountry.subdivisions.get(
                    country_code=country.alpha2
                )
            except KeyError:
                pass
            else:
                for subdivision in list(divisions)[0:count]:
                    self.Subdivision.create([{
                        'country': countries[0].id,
                        'name': subdivision.name,
                        'code': subdivision.code,
                        'type': subdivision.type.lower(),
                    }])

    def create_payment_profile(self, party, gateway):
        """
        Create a payment profile for the party
        """
        AddPaymentProfileWizard = POOL.get(
            'party.party.payment_profile.add', type='wizard'
        )

        # create a profile
        profile_wiz = AddPaymentProfileWizard(
            AddPaymentProfileWizard.create()[0]
        )
        profile_wiz.card_info.party = party.id
        profile_wiz.card_info.address = party.addresses[0].id
        profile_wiz.card_info.provider = gateway.provider
        profile_wiz.card_info.gateway = gateway
        profile_wiz.card_info.owner = party.name
        profile_wiz.card_info.number = '4111111111111111'
        profile_wiz.card_info.expiry_month = '11'
        profile_wiz.card_info.expiry_year = '2018'
        profile_wiz.card_info.csc = '353'

        with Transaction().set_context(return_profile=True):
            return profile_wiz.transition_add()

    def setup_defaults(self):
        """Creates default data for testing
        """
        self.currency, = self.Currency.create([{
            'name': 'US Dollar',
            'code': 'USD',
            'symbol': '$',
        }])

        with Transaction().set_context(company=None):
            company_party, = self.Party.create([{
                'name': 'openlabs'
            }])
            employee_party, = self.Party.create([{
                'name': 'Jim'
            }])

        self.company, = self.Company.create([{
            'party': company_party,
            'currency': self.currency,
        }])

        self.employee, = self.Employee.create([{
            'party': employee_party.id,
            'company': self.company.id,
        }])

        self.User.write([self.User(USER)], {
            'company': self.company,
            'main_company': self.company,
            'employees': [('add', [self.employee.id])],
        })
        # Write employee separately as employees needs to be saved first
        self.User.write([self.User(USER)], {
            'employee': self.employee.id,
        })

        CONTEXT.update(self.User.get_preferences(context_only=True))

        # Create Fiscal Year
        self._create_fiscal_year(company=self.company.id)
        # Create Chart of Accounts
        self._create_coa_minimal(company=self.company.id)
        # Create a payment term
        self.payment_term, = self._create_payment_term()
        self.cash_journal, = self.Journal.search(
            [('type', '=', 'cash')], limit=1
        )

        self.country, = self.Country.create([{
            'name': 'United States of America',
            'code': 'US',
        }])

        self.subdivision, = self.Subdivision.create([{
            'country': self.country.id,
            'name': 'California',
            'code': 'CA',
            'type': 'state',
        }])

        # Create party
        self.party, = self.Party.create([{
            'name': 'Bruce Wayne',
            'addresses': [('create', [{
                'name': 'Bruce Wayne',
                'city': 'Gotham',
                'country': self.country.id,
                'subdivision': self.subdivision.id,
            }])],
            'customer_payment_term': self.payment_term.id,
            'account_receivable': self._get_account_by_kind(
                'receivable').id,
            'contact_mechanisms': [('create', [
                {'type': 'mobile', 'value': '8888888888'},
            ])],
        }])


class TestSale(BaseTestCase):
    """Test Sale with Payments
    """

    def test_0005_payment(self):
        """
        Check payment total fields
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.currency,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'company': self.company.id,

                'invoice_method': 'manual',
                'shipment_method': 'manual',

                'lines': [('create', [{
                    'description': 'Some item',
                    'unit_price': Decimal('100'),
                    'quantity': 1
                }])]
            }])
            self.assertEqual(sale.total_amount, Decimal('100'))
            self.assertEqual(sale.payment_total, Decimal('0'))
            self.assertEqual(sale.amount_payment_received, Decimal('0'))
            self.assertEqual(sale.amount_payment_in_progress, Decimal('0'))
            self.assertEqual(sale.payment_captured, Decimal('0'))
            self.assertEqual(sale.payment_authorized, Decimal('0'))

            with Transaction().set_context(use_dummy=True):
                # Create a gateway
                gateway, = self.PaymentGateway.create([{
                    'name': 'Dummy Gateway',
                    'journal': self.cash_journal.id,
                    'provider': 'dummy',
                    'method': 'credit_card',
                }])

                # Create a payment profile
                payment_profile = self.create_payment_profile(
                    self.party, gateway
                )

                # Create a payment
                payment, = self.SalePayment.create([{
                    'sale': sale.id,
                    'amount': Decimal('100'),
                    'gateway': gateway,
                    'payment_profile': payment_profile.id
                }])
                self.assertEqual(payment.provider, 'dummy')

            self.assertEqual(sale.total_amount, Decimal('100'))
            self.assertEqual(sale.payment_total, Decimal('100'))
            self.assertEqual(sale.payment_remaining, Decimal('100'))
            self.assertEqual(sale.amount_payment_received, Decimal('0'))
            self.assertEqual(sale.amount_payment_in_progress, Decimal('0'))
            self.assertEqual(sale.payment_captured, Decimal('0'))
            self.assertEqual(sale.payment_authorized, Decimal('0'))

            with Transaction().set_context(company=self.company.id):
                # authorize money directly from payment
                payment.authorize(Decimal('50'), 'Test')

                with self.assertRaises(UserError):
                    payment.authorize(Decimal('500'), 'Test')

                # Try raising payment for more money that available
                with self.assertRaises(UserError):
                    sale.authorize_from_sale_payments(Decimal(101), 'For fun')

    def test_0010_partial_payment_authorize(self):
        """
        Check the functionality to use payment.
        """
        SalePayment = POOL.get('sale.payment')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'company': self.company.id,

                'invoice_method': 'manual',
                'shipment_method': 'manual',

                'lines': [('create', [{
                    'description': 'Some item',
                    'unit_price': Decimal('100'),
                    'quantity': 1
                }])]
            }])

            with Transaction().set_context(use_dummy=True):
                # Create gateways
                cash_gateway, dummy_gateway, = self.PaymentGateway.create([
                    {
                        'name': 'Cash Gateway',
                        'journal': self.cash_journal.id,
                        'provider': 'self',
                        'method': 'manual',
                    }, {
                        'name': 'Dummy Gateway',
                        'journal': self.cash_journal.id,
                        'provider': 'dummy',
                        'method': 'credit_card',
                    }
                ])

                # Create a payment profile
                payment_profile = self.create_payment_profile(
                    self.party, dummy_gateway
                )

                # Create a payment for $50 in cash and $50 in card
                payment_cash, payment_card = SalePayment.create([
                    {
                        'sale': sale.id,
                        'amount': Decimal('50'),
                        'gateway': cash_gateway,
                    },
                    {
                        'sale': sale.id,
                        'amount': Decimal('50'),
                        'payment_profile': payment_profile.id,
                        'gateway': dummy_gateway,
                    }
                ])

            self.assertEqual(sale.total_amount, Decimal('100'))
            self.assertEqual(sale.payment_total, Decimal('100'))
            self.assertEqual(sale.payment_remaining, Decimal('100'))
            self.assertEqual(sale.amount_payment_received, Decimal('0'))
            self.assertEqual(sale.amount_payment_in_progress, Decimal('0'))
            self.assertEqual(sale.payment_captured, Decimal('0'))
            self.assertEqual(sale.payment_authorized, Decimal('0'))

            # Ask for an authorization of $60. $50 should come from
            # AR (based on the cash payment) and the remaining $10 from
            # credit card authorization
            transactions = sale.authorize_from_sale_payments(
                Decimal('60'), 'Shipment 1'
            )
            self.assertEqual(len(transactions), 2)

            # A payment transaction with authorized state for $50
            self.assertEqual(transactions[0].state, 'authorized')
            self.assertEqual(transactions[0].method, 'manual')
            self.assertEqual(transactions[0].amount, Decimal('50'))
            self.assertEqual(transactions[0].sale, sale)

            # A payment transaction with authorized state for $10
            self.assertEqual(transactions[1].state, 'authorized')
            self.assertEqual(transactions[1].method, 'credit_card')
            self.assertEqual(
                transactions[1].amount, Decimal('10')
            )
            self.assertEqual(transactions[1].sale, sale)

            # Check the balances again
            self.assertEqual(sale.total_amount, Decimal('100'))
            self.assertEqual(sale.payment_total, Decimal('100'))

            # Since the settlement is not done this will be 40
            self.assertEqual(sale.payment_remaining, Decimal('40'))
            self.assertEqual(sale.amount_payment_received, Decimal('0'))
            self.assertEqual(
                sale.amount_payment_in_progress, Decimal('50') + Decimal('10')
            )
            self.assertEqual(sale.payment_captured, Decimal('0'))
            self.assertEqual(
                sale.payment_authorized, Decimal('50') + Decimal('10')
            )


def suite():
    """
    Define suite
    """
    test_suite = trytond.tests.test_tryton.suite()
    test_suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestSale)
    )
    return test_suite

if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
