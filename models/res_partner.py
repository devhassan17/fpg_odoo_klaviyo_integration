# -*- coding: utf-8 -*-

import json
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
        related='x_marketing_opt_in',
        readonly=False,
        store=True,
        help='If checked, this contact has opted in to receive marketing emails via Klaviyo.',
        tracking=True,
    )
    klaviyo_subscription_log = fields.Text(
        string='Klaviyo Subscription Log',
        readonly=True,
        help='Diagnostic log from the last Klaviyo subscription attempt.',
    )

    def write(self, vals):
        res = super(ResPartner, self).write(vals)
        # Trigger subscription if:
        # 1. klaviyo_marketing_opt_in or x_marketing_opt_in is being set to True
        # 2. Or, email is being changed/set AND either is True
        opt_in_changed = (
            ('klaviyo_marketing_opt_in' in vals and vals.get('klaviyo_marketing_opt_in')) or
            ('x_marketing_opt_in' in vals and vals.get('x_marketing_opt_in'))
        )
        email_changed = 'email' in vals and self.filtered(lambda p: p.klaviyo_marketing_opt_in or p.x_marketing_opt_in)
        if opt_in_changed or email_changed:
            _logger.info(
                "Klaviyo: write() triggered subscription flow. "
                "opt_in_changed=%s, email_changed=%s, partner_ids=%s",
                opt_in_changed, bool(email_changed), self.ids
            )
            for partner in self:
                if (partner.klaviyo_marketing_opt_in or partner.x_marketing_opt_in) and partner.email:
                    partner._subscribe_to_klaviyo()
                else:
                    _logger.info(
                        "Klaviyo: Skipping partner %s (id=%s) — opt_in=%s, email=%s",
                        partner.name, partner.id, partner.klaviyo_marketing_opt_in or partner.x_marketing_opt_in, partner.email
                    )
        return res

    @api.model_create_multi
    def create(self, vals_list):
        partners = super(ResPartner, self).create(vals_list)
        for partner in partners:
            if (partner.klaviyo_marketing_opt_in or partner.x_marketing_opt_in) and partner.email:
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

        # Use an ISO 8601 / RFC 3339 UTC timestamp in the past
        consented_at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        _logger.info(
            "Klaviyo Subscription: Profile data — email=%s, consented_at=%s",
            self.email, consented_at
        )

        # Prepare payload — only email + subscriptions are valid for this endpoint
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

    def action_test_klaviyo_subscription(self):
        """Button action: test the Klaviyo subscription and show results in the UI."""
        self.ensure_one()
        log_lines = []
        log_lines.append(f"=== Klaviyo Subscription Test ===")
        log_lines.append(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        log_lines.append(f"Partner: {self.name} (id={self.id})")
        log_lines.append(f"Email: {self.email}")
        log_lines.append(f"Opt-In: {self.klaviyo_marketing_opt_in}")
        log_lines.append("")

        if not self.email:
            log_lines.append("❌ ABORTED: No email address on this contact.")
            self.klaviyo_subscription_log = '\n'.join(log_lines)
            return self._klaviyo_notify('No email address', 'danger')

        # Step 1: API Key
        try:
            is_test, api_key = self.env['res.config.settings'].get_klaviyo_api_key()
            log_lines.append(f"Step 1 - API Key: is_test={is_test}, key_present={bool(api_key)}")
            if api_key:
                log_lines.append(f"  Key prefix: {api_key[:6]}...")
        except Exception as e:
            log_lines.append(f"Step 1 - API Key: ❌ EXCEPTION: {e}")
            self.klaviyo_subscription_log = '\n'.join(log_lines)
            return self._klaviyo_notify(f'API Key error: {e}', 'danger')

        if not api_key:
            log_lines.append("❌ ABORTED: Private API Key is missing.")
            self.klaviyo_subscription_log = '\n'.join(log_lines)
            return self._klaviyo_notify('Private API Key is missing', 'danger')

        # Step 2: Fetch Lists
        headers = KLAVIYO_HEADERS.copy()
        headers["Authorization"] = headers["Authorization"] % api_key
        try:
            lists_response = requests.get(
                url='https://a.klaviyo.com/api/lists',
                headers=headers,
                timeout=10
            )
            log_lines.append(f"Step 2 - Fetch Lists: status={lists_response.status_code}")
            if lists_response.status_code == 200:
                lists_data = lists_response.json().get('data', [])
                for lst in lists_data:
                    lid = lst.get('id')
                    lname = lst.get('attributes', {}).get('name', 'N/A')
                    log_lines.append(f"  List: '{lname}' (id={lid})")
                if not lists_data:
                    log_lines.append("  ⚠️ No lists found in Klaviyo account!")
            else:
                log_lines.append(f"  ❌ Response: {lists_response.text[:300]}")
        except Exception as e:
            log_lines.append(f"Step 2 - Fetch Lists: ❌ EXCEPTION: {e}")
            self.klaviyo_subscription_log = '\n'.join(log_lines)
            return self._klaviyo_notify(f'Lists fetch error: {e}', 'danger')

        # Step 3: Resolve List ID
        list_id = self._get_klaviyo_list_id(api_key)
        log_lines.append(f"Step 3 - Resolved List ID: {list_id}")
        if not list_id:
            log_lines.append("❌ ABORTED: Could not resolve a list ID.")
            self.klaviyo_subscription_log = '\n'.join(log_lines)
            return self._klaviyo_notify('No Klaviyo list found', 'danger')

        # Step 4: Build & Send Payload
        consented_at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Only email + subscriptions are valid for this endpoint
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

        log_lines.append(f"Step 4 - Payload built:")
        log_lines.append(f"  email={self.email}")
        log_lines.append(f"  consented_at={consented_at}")
        log_lines.append(f"  list_id={list_id}")
        log_lines.append(f"  historical_import=True")
        log_lines.append(f"  URL: {KLAVIYO_SUBSCRIBE_URL}")
        log_lines.append(f"  Revision: {headers.get('revision')}")
        log_lines.append("")

        try:
            response = requests.post(
                url=KLAVIYO_SUBSCRIBE_URL,
                json=payload,
                headers=headers,
                timeout=10
            )
            log_lines.append(f"Step 5 - API Response:")
            log_lines.append(f"  Status Code: {response.status_code}")
            log_lines.append(f"  Response Body: {response.text[:500] if response.text else '(empty)'}")

            if response.status_code in (200, 202):
                log_lines.append("")
                log_lines.append("✅ SUCCESS — Subscription request accepted by Klaviyo.")
                self.klaviyo_subscription_log = '\n'.join(log_lines)
                return self._klaviyo_notify(f'Success! Status {response.status_code}. Check Klaviyo in ~30 seconds.', 'success')
            else:
                log_lines.append("")
                log_lines.append(f"❌ FAILED — Klaviyo returned status {response.status_code}")
                self.klaviyo_subscription_log = '\n'.join(log_lines)
                return self._klaviyo_notify(f'Failed: {response.status_code} — {response.text[:200]}', 'danger')
        except Exception as e:
            log_lines.append(f"Step 5 - ❌ EXCEPTION: {e}")
            self.klaviyo_subscription_log = '\n'.join(log_lines)
            return self._klaviyo_notify(f'Exception: {e}', 'danger')

    def _klaviyo_notify(self, message, notif_type='info'):
        """Return a notification action."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Klaviyo Subscription',
                'message': message,
                'type': notif_type,
                'sticky': True,
            }
        }
