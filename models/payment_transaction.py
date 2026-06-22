# -*- coding: utf-8 -*-

from odoo import models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _set_done(self, *args, **kwargs):
        """Ref: https://www.odoo.com/documentation/19.0/developer/reference/standard_modules/payment/payment_transaction.html
        """
        res = super()._set_done(*args, **kwargs)

        # Check company filter
        if not self.env['res.config.settings'].check_klaviyo_company(self.company_id):
            return res

        # Get Sale Order by Reference
        # Get the Order Name from these cases: S00300-1, S00300-2
        idx = self.reference.find('-')
        reference = self.reference if idx == -1 else self.reference[:idx]
        order_id = self.env['sale.order'].search([('name', 'ilike', reference)])
        if order_id:
            # Put Klaviyo Event into the Queue if not already queued
            event_queue = self.env['fpg.odoo.klaviyo.integration.event.queue']
            existing_event = event_queue.search([('transaction_id', '=', self.id)], limit=1)
            if not existing_event:
                event_queue.create({
                    'order_id': order_id.id,
                    'transaction_id': self.id
                })
        # Return Transaction
        return res
