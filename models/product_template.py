# -*- coding: utf-8 -*-

from werkzeug import urls

from odoo import models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _get_combination_info(
        self, combination=False, product_id=False, add_qty=1.0,
        parent_combination=False, only_template=False,
    ):
        res = super()._get_combination_info(
            combination, product_id, add_qty,
            parent_combination, only_template
        )
        res.update({
            'url': self._get_item_url(),
            'image_url': self.website_meta_og_img or ''
        })
        return res

    def _get_item_url(self):
        if self.type == 'service':
            return None
        website_base_url = self.env.company.get_base_url()
        if website_base_url in self.website_url:
            return self.website_url
        return urls.url_join(website_base_url, self.website_url)
