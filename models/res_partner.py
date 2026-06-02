# -*- coding: utf-8 -*-

import logging
import requests
from datetime import datetime, timezone, timedelta
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

    klaviyo_marketing_opt_in = fields.Boolean(
        string='Klaviyo Marketing Opt-In',
        default=False,
        help='If checked, this contact has opted in to receive marketing emails via Klaviyo.',
        tracking=True,
    )

    def write(self, vals):
        res = super(ResPartner, self).write(vals)
        # Trigger subscription if:
        # 1. klaviyo_marketing_opt_in is being set to True
        # 2. Or, email is being changed/set AND klaviyo_marketing_opt_in is True
        if ('klaviyo_marketing_opt_in' in vals and vals.get('klaviyo_marketing_opt_in')) or \
           ('email' in vals and self.filtered(lambda p: p.klaviyo_marketing_opt_in)):
            for partner in self:
                if partner.klaviyo_marketing_opt_in and partner.email:
                    partner._subscribe_to_klaviyo()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        partners = super(ResPartner, self).create(vals_list)
        for partner in partners:
            if partner.klaviyo_marketing_opt_in and partner.email:
                partner._subscribe_to_klaviyo()
        return partners

    def _get_klaviyo_list_id(self, api_key):
        """Helper to get an existing list ID on Klaviyo to subscribe the profile to.
        Never creates a new list.
        """
        headers = KLAVIYO_HEADERS.copy()
        headers["Authorization"] = headers["Authorization"] % api_key

        try:
            # Fetch existing lists
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
        except Exception as e:
            _logger.exception("Exception occurred while resolving Klaviyo List ID")
        return False

    def _subscribe_to_klaviyo(self):
        """Subscribe the partner's email to Klaviyo with email consent immediately.
        Uses historical_import=True to bypass double opt-in confirmation.
        """
        # We need the API key
        is_test, api_key = self.env['res.config.settings'].get_klaviyo_api_key()
        if not api_key:
            _logger.warning("Klaviyo Subscription: Private API Key is missing.")
            return

        # Resolve list_id dynamically (without creating any new list)
        list_id = self._get_klaviyo_list_id(api_key)
        if not list_id:
            _logger.warning("Klaviyo Subscription: Unable to resolve any subscription list ID.")
            return

        # Safely fetch split names if available
        first_name = getattr(self, 'x_first_name', '') or self.name or ''
        last_name = getattr(self, 'x_last_name', '') or ''

        # Use an ISO 8601 UTC timestamp slightly in the past
        consented_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Prepare payload
        payload = {
            "data": {
                "type": "profile-subscription-bulk-create-job",
                "attributes": {
                    "historical_import": True,
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
                                                "consent": "SUBSCRIBED",
                                                "consented_at": consented_at
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
                _logger.info("Successfully subscribed %s to Klaviyo (Double Opt-in Bypassed)", self.email)
        except Exception as e:
            _logger.exception("Exception occurred while subscribing %s to Klaviyo", self.email)
