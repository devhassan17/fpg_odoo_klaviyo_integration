# -*- coding: utf-8 -*-

import json
import logging
import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

KLAVIYO_SUBSCRIBE_URL = 'https://a.klaviyo.com/api/profile-subscription-bulk-create-jobs/'
KLAVIYO_HEADERS = {
    "Accept": "application/vnd.api+json",
    "revision": "2024-10-15",
    "content-type": "application/vnd.api+json",
    "Authorization": "Klaviyo-API-Key %s"
}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        res = super(ResPartner, self).write(vals)
        # Trigger subscription if:
        # 1. x_marketing_opt_in is being set to True
        # 2. Or, email is being changed/set AND x_marketing_opt_in is True
        if ('x_marketing_opt_in' in vals and vals.get('x_marketing_opt_in')) or ('email' in vals and self.filtered(lambda p: p.x_marketing_opt_in)):
            for partner in self:
                if partner.x_marketing_opt_in and partner.email:
                    partner._subscribe_to_klaviyo()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        partners = super(ResPartner, self).create(vals_list)
        for partner in partners:
            if partner.x_marketing_opt_in and partner.email:
                partner._subscribe_to_klaviyo()
        return partners

    def _subscribe_to_klaviyo(self):
        """Subscribe the partner's email to Klaviyo with email consent.
        """
        # We need the API key
        is_test, api_key = self.env['res.config.settings'].get_klaviyo_api_key()
        if not api_key:
            _logger.warning("Klaviyo Subscription: Private API Key is missing.")
            return

        # We need the List ID from the website settings
        website = self.env['website'].get_current_website()
        list_id = website.klaviyo_subscription_list_id if website else False
        if not list_id:
            # Fallback to the first website that has list_id configured, or log a warning
            website = self.env['website'].search([('klaviyo_subscription_list_id', '!=', False)], limit=1)
            list_id = website.klaviyo_subscription_list_id if website else False

        if not list_id:
            _logger.warning("Klaviyo Subscription: Subscription List ID is not configured on any website.")
            return

        # Safely fetch split names if available
        first_name = getattr(self, 'x_first_name', '') or self.name or ''
        last_name = getattr(self, 'x_last_name', '') or ''

        # Prepare payload
        payload = {
            "data": {
                "type": "profile-subscription-bulk-create-job",
                "attributes": {
                    "profiles": {
                        "data": [
                            {
                                "type": "profile",
                                "attributes": {
                                    "email": self.email,
                                    "first_name": first_name,
                                    "last_name": last_name,
                                    "subscriptions": {
                                        "email": {
                                            "marketing": {
                                                "consent": "SUBSCRIBED"
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    },
                    "custom_source": "Odoo Marketing Consent Checkbox"
                },
                "relationships": {
                    "list": {
                        "data": {
                            "type": "list",
                            "id": list_id
                        }
                    }
                }
            }
        }

        headers = KLAVIYO_HEADERS.copy()
        headers["Authorization"] = headers["Authorization"] % api_key

        try:
            response = requests.post(
                url=KLAVIYO_SUBSCRIBE_URL,
                json=payload,
                headers=headers,
                timeout=5
            )
            if response.status_code not in (200, 202):
                _logger.error(
                    "Klaviyo Subscription failed for %s. Code: %s, Response: %s",
                    self.email, response.status_code, response.text
                )
            else:
                _logger.info("Successfully requested Klaviyo subscription for %s", self.email)
        except Exception as e:
            _logger.exception("Exception occurred while subscribing %s to Klaviyo", self.email)
