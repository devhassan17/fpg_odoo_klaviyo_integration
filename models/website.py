# -*- coding: utf-8 -*-

from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    klaviyo_public_key = fields.Char(
        string='Klaviyo Public Key'
    )
