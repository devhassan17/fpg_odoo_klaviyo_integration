# -*- coding: utf-8 -*-

import ast
import requests

from odoo import api, fields, models

from .klaviyo_event_queue import KLAVIYO_URL, KLAVIYO_HEADERS


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    has_klaviyo = fields.Boolean(
        string="Klaviyo",
        config_parameter='fpg_odoo_klaviyo_integration.has_klaviyo',
        default=False
    )
    klaviyo_public_key = fields.Char(
        string='Klaviyo Public Key',
        related='website_id.klaviyo_public_key',
        readonly=False
    )
    klaviyo_company_id = fields.Many2one(
        'res.company',
        string='Klaviyo Company',
        config_parameter='fpg_odoo_klaviyo_integration.klaviyo_company_id',
        help='Select the company for which this Klaviyo integration is active. Leave empty to allow all companies.'
    )

    @api.model
    def check_klaviyo_company(self, company=False):
        """Check if Klaviyo integration is active for the given company.
        If no company is configured in settings, it is active for all.
        """
        configured_company_id = self.env['ir.config_parameter'].sudo().get_param('fpg_odoo_klaviyo_integration.klaviyo_company_id')
        if not configured_company_id:
            return True
        check_company = company or self.env.company
        return check_company and check_company.id == int(configured_company_id)

    @api.onchange('has_klaviyo')
    def _onchange_has_klaviyo(self):
        if not self.has_klaviyo:
            self.klaviyo_public_key = False

    def action_test_connection(self):
        """Test access
        """
        config = self.env['res.config.settings']
        is_test, api_key = config.get_klaviyo_api_key()
        response = requests.get(
            url=KLAVIYO_URL,
            headers=ast.literal_eval(KLAVIYO_HEADERS % (api_key,)),
            timeout=10
        )
        return config.get_test_notification({
            'code': response.status_code,
            'action': 'Events',
            'scope': 'Integration'
        })
