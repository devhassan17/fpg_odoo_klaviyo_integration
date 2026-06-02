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
