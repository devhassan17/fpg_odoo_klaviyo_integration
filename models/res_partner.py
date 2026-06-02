# -*- coding: utf-8 -*-

import logging
import requests
from datetime import datetime, timezone, timedelta
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

KLAVIYO_SUBSCRIBE_URL = 'https://a.klaviyo.com/api/profile-subscription-bulk-create-jobs/'
KLAVIYO_HEADERS = {
    "Accept": "application/vnd.api+json",
    "revision": "2025-01-15",
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
        opt_in_changed = 'klaviyo_marketing_opt_in' in vals and vals.get('klaviyo_marketing_opt_in')
        email_changed = 'email' in vals and self.filtered(lambda p: p.klaviyo_marketing_opt_in)
        if opt_in_changed or email_changed:
            _logger.info(
                "Klaviyo: write() triggered subscription flow. "
                "opt_in_changed=%s, email_changed=%s, partner_ids=%s",
                opt_in_changed, bool(email_changed), self.ids
            )
            for partner in self:
                if partner.klaviyo_marketing_opt_in and partner.email:
                    partner._subscribe_to_klaviyo()
                else:
                    _logger.info(
                        "Klaviyo: Skipping partner %s (id=%s) — opt_in=%s, email=%s",
                        partner.name, partner.id, partner.klaviyo_marketing_opt_in, partner.email
                    )
        return res

    @api.model_create_multi
    def create(self, vals_list):
        partners = super(ResPartner, self).create(vals_list)
        for partner in partners:
            if partner.klaviyo_marketing_opt_in and partner.email:
                _logger.info(
                    "Klaviyo: create() triggered subscription for %s (id=%s)",
                    partner.email, partner.id
                )
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
            _logger.info("Klaviyo: Fetching available lists from Klaviyo API...")
            response = requests.get(
                url='https://a.klaviyo.com/api/lists',
                headers=headers,
                timeout=10
            )
            _logger.info("Klaviyo: Lists API response code: %s", response.status_code)
            if response.status_code == 200:
                lists_data = response.json().get('data', [])
                # Log all available lists for debugging
                list_names = [
                    f"{lst.get('id')} => {lst.get('attributes', {}).get('name', 'N/A')}"
                    for lst in lists_data
                ]
                _logger.info("Klaviyo: Available lists: %s", list_names)
                # First check for names containing newsletter, subscriber, or marketing
                for lst in lists_data:
                    name = lst.get('attributes', {}).get('name', '').lower()
                    if 'newsletter' in name or 'subscriber' in name or 'marketing' in name:
                        _logger.info("Klaviyo: Matched list '%s' (id=%s)", name, lst.get('id'))
                        return lst.get('id')
                # If no match, use the first list
                if lists_data:
                    fallback_id = lists_data[0].get('id')
                    fallback_name = lists_data[0].get('attributes', {}).get('name', 'N/A')
                    _logger.info("Klaviyo: No keyword match, falling back to first list '%s' (id=%s)", fallback_name, fallback_id)
                    return fallback_id
                else:
                    _logger.warning("Klaviyo: No lists found in the Klaviyo account!")
            else:
                _logger.error("Klaviyo: Failed to fetch lists. Code: %s, Response: %s", response.status_code, response.text)
        except Exception as e:
            _logger.exception("Exception occurred while resolving Klaviyo List ID")
        return False

    def _subscribe_to_klaviyo(self):
        """Subscribe the partner's email to Klaviyo with email consent immediately.
        Uses historical_import=True to bypass double opt-in confirmation.
        """
        _logger.info("Klaviyo Subscription: === START === Attempting to subscribe %s (partner ID: %s)", self.email, self.id)

        # We need the API key
        is_test, api_key = self.env['res.config.settings'].get_klaviyo_api_key()
        _logger.info("Klaviyo Subscription: is_test=%s, api_key_present=%s", is_test, bool(api_key))
        if not api_key:
            _logger.warning("Klaviyo Subscription: Private API Key is missing. Aborting.")
            return

        # Resolve list_id dynamically (without creating any new list)
        list_id = self._get_klaviyo_list_id(api_key)
        if not list_id:
            _logger.warning("Klaviyo Subscription: Unable to resolve any subscription list ID. Aborting.")
            return

        _logger.info("Klaviyo Subscription: Using list ID '%s' for %s", list_id, self.email)

        # Safely fetch split names if available
        first_name = getattr(self, 'x_first_name', '') or self.name or ''
        last_name = getattr(self, 'x_last_name', '') or ''

        # Use an ISO 8601 UTC timestamp slightly in the past
        consented_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        _logger.info(
            "Klaviyo Subscription: Profile data — email=%s, first_name=%s, last_name=%s, consented_at=%s",
            self.email, first_name, last_name, consented_at
        )

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

        _logger.info("Klaviyo Subscription: Sending payload to %s", KLAVIYO_SUBSCRIBE_URL)
        _logger.debug("Klaviyo Subscription: Full payload: %s", payload)

        headers = KLAVIYO_HEADERS.copy()
        headers["Authorization"] = headers["Authorization"] % api_key

        try:
            response = requests.post(
                url=KLAVIYO_SUBSCRIBE_URL,
                json=payload,
                headers=headers,
                timeout=10
            )
            _logger.info(
                "Klaviyo Subscription: Response — status=%s, body=%s",
                response.status_code, response.text[:500] if response.text else '(empty)'
            )
            if response.status_code not in (200, 202):
                _logger.error(
                    "Klaviyo Subscription FAILED for %s. Code: %s, Full Response: %s",
                    self.email, response.status_code, response.text
                )
            else:
                _logger.info("Klaviyo Subscription SUCCESS for %s (status: %s)", self.email, response.status_code)
        except Exception as e:
            _logger.exception("Klaviyo Subscription EXCEPTION for %s", self.email)

        _logger.info("Klaviyo Subscription: === END === for %s", self.email)
