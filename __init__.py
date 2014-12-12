# -*- coding: utf-8 -*-
"""
    __init__.py

    :copyright: (c) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from trytond.pool import Pool

from sale import Sale, AddSalePaymentView, AddSalePayment
from payment import SalePayment
from transaction import PaymentTransaction
from invoice import Invoice


def register():
    Pool.register(
        Sale,
        SalePayment,
        PaymentTransaction,
        AddSalePaymentView,
        Invoice,
        module='sale_payment', type_='model'
    )
    Pool.register(
        AddSalePayment,
        module='sale_payment', type_='wizard'
    )
