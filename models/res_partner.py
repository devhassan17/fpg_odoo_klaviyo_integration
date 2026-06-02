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

    def _get_or_create_klaviyo_list_id(self, api_key):
        """Helper to get or create a list ID on Klaviyo to subscribe the profile to.
        """
        headers = KLAVIYO_HEADERS.copy()
        headers["Authorization"] = headers["Authorization"] % api_key

        try:
            # 1. Fetch existing lists
            response = requests.get(
                url='https://a.klaviyo.com/api/lists',
                headers=headers,
                timeout=5
            )
            if response.status_code == 200:
                lists_data = response.json().get('data', [])
                # First check for names containing newsletter, subscriber, or marketing
                for lst in lists_data:
                    name = lst.get('attributes', {}).get('name', '').lower()
                    if 'newsletter' in name or 'subscriber' in name or 'marketing' in name:
                        return lst.get('id')
                # If no match, use the first list
                if lists_data:
                    return lists_data[0].get('id')

            # 2. If no lists exist, create a new one named "Newsletter"
            create_payload = {
                "data": {
                    "type": "list",
                    "attributes": {
                        "name": "Newsletter"
                    }
                }
            }
            create_response = requests.post(
                url='https://a.klaviyo.com/api/lists',
                json=create_payload,
                headers=headers,
                timeout=5
            )
            if create_response.status_code in (200, 201, 202):
                return create_response.json().get('data', {}).get('id')
            else:
                _logger.error(
                    "Klaviyo List creation failed. Code: %s, Response: %s",
                    create_response.status_code, create_response.text
                )
        except Exception as e:
            _logger.exception("Exception occurred while resolving Klaviyo List ID")
        return False

    def _subscribe_to_klaviyo(self):
        """Subscribe the partner's email to Klaviyo with email consent.
        """
        # We need the API key
        is_test, api_key = self.env['res.config.settings'].get_klaviyo_api_key()
        if not api_key:
            _logger.warning("Klaviyo Subscription: Private API Key is missing.")
            return

        # Resolve list_id dynamically
        list_id = self._get_or_create_klaviyo_list_id(api_key)
        if not list_id:
            _logger.warning("Klaviyo Subscription: Unable to resolve subscription list ID.")
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
