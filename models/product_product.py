# -*- coding: utf-8 -*-

from odoo import models


class Product(models.Model):
    _inherit = "product.product"

    def _get_item_url(self):
        return self.product_tmpl_id._get_item_url()
