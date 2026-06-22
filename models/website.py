# -*- coding: utf-8 -*-

from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    klaviyo_public_key = fields.Char(
        string='Klaviyo Public Key'
    )

    def is_klaviyo_enabled(self):
        """Check if Klaviyo is enabled and matches the company filter."""
        self.ensure_one()
        if not self.klaviyo_public_key:
            return False
        return self.env['res.config.settings'].check_klaviyo_company(self.company_id)

    def _get_klaviyo_checkout_partner(self):
        """Safely retrieve the checkout partner for Klaviyo tracking.
        Uses hasattr and try-except on the backend to avoid QWeb evaluation context issues.
        """
        self.ensure_one()
        if hasattr(self, 'sale_get_order'):
            try:
                order = self.sale_get_order()
                if order and order.partner_id and order.partner_id.email:
                    public_partner = self.user_id.sudo().partner_id
                    if order.partner_id.id != public_partner.id and order.partner_id.email != public_partner.email:
                        return order.partner_id
            except Exception:
                pass
        return False
