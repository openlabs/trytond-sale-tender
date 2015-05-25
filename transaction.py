# -*- coding: utf-8 -*-
"""
    transaction.py

    :copyright: (c) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from trytond.model import fields
from trytond.pyson import Eval
from trytond.pool import PoolMeta

__metaclass__ = PoolMeta
__all__ = ['PaymentTransaction']


class PaymentTransaction:
    __name__ = 'payment_gateway.transaction'

    payment = fields.Many2One(
        'sale.payment', 'Payment',
        domain=[('sale', '=', Eval('sale'))],
        depends=['sale'],
        readonly=True, select=True
    )
