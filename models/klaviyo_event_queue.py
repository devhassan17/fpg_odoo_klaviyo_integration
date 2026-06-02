# -*- coding: utf-8 -*-

import ast
import json
import logging
import requests

from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError

from odoo import fields, models

_logger = logging.getLogger(__name__)

KLAVIYO_URL = 'https://a.klaviyo.com/api/events'
KLAVIYO_HEADERS = '{' \
                  '  "Accept": "application/vnd.api+json",' \
                  '  "revision": "2025-01-15", "content-type": "application/vnd.api+json",' \
                  '  "Authorization": "Klaviyo-API-Key %s"' \
                  '}'


class KlaviyoEventQueue(models.Model):
    _name = 'fpg.odoo.klaviyo.integration.event.queue'
    _order = 'create_date desc'
    _rec_name = 'order_id'

    order_id = fields.Many2one(
        'sale.order',
        string='Sale Order'
    )
    transaction_id = fields.Many2one(
        'payment.transaction',
        string='Payment Transaction'
    )
    payment_method_id = fields.Many2one(
        related='transaction_id.payment_method_id',
        string='Payment Method'
    )
    provider_id = fields.Many2one(
        related='transaction_id.provider_id',
        string='Provider'
    )
    partner_id = fields.Many2one(
        related='transaction_id.partner_id',
        string='Customer'
    )
    retries = fields.Integer(
        string='Retries',
        default=0
    )
    state = fields.Selection(
        selection=[
            ('waiting', 'Waiting'),
            ('sent', 'Sent'),
            ('canceled', 'Cancelled'),
        ],
        string='Status',
        readonly=True,
        copy=False,
        index=True,
        default='waiting'
    )
    message = fields.Char(
        string='Event Message'
    )

    def send_event(self):
        """Send Klaviyo Event to achieve Customer Lifetime Value (CLV)
        """
        # Start Event Processing
        api_key = self._get_klaviyo_api_key()
        if not api_key:
            return
        # Send events
        for event in self.search([('state', '=', 'waiting')]):
            payload = self._build_payload(event=event)
            response = requests.post(
                url=KLAVIYO_URL,
                json=payload,
                headers=ast.literal_eval(KLAVIYO_HEADERS % (api_key,)),
                timeout=5
            )
            data = {}
            if response.status_code == 202:
                data.update({
                    'state': 'sent',
                    'message': 'Sent OK'
                })
                # Auto-subscribe partner if opted in
                partner = event.partner_id or event.order_id.partner_id
                if partner and partner.email and (partner.klaviyo_marketing_opt_in or partner.x_marketing_opt_in):
                    try:
                        _logger.info("Klaviyo: Auto-subscribing partner %s (id=%s) during order event sending", partner.name, partner.id)
                        partner._subscribe_to_klaviyo()
                    except Exception as e:
                        _logger.exception("Klaviyo: Failed to auto-subscribe partner %s during event processing", partner.id)
            else:
                try:
                    data.update({
                        'message': f'{response.status_code}:{json.dumps(response.json().get('errors'))}'
                    })
                except RequestsJSONDecodeError:
                    data.update({
                        'message': 'Unable to parse request response'
                    })
                # Count retries and no more retries after 3 attempts
                retries = event.retries + 1
                data.update({
                    'retries': retries
                })
                if retries >= 3:
                    data.update({
                        'state': 'canceled'
                    })
            # Write
            event.write(data)

    def _get_klaviyo_api_key(self):
        """Get the API Key
        """
        is_test, api_key = self.env['res.config.settings'].get_klaviyo_api_key()
        if not is_test and not api_key:
            self.write({
                'message': 'Production Private API Key is missing'
            })
            return False
        if is_test and not api_key:
            self.write({
                'message': 'Test Private API Key is missing'
            })
            return False
        return api_key

    def _build_payload(self, event):
        """Build the Payload of the Event
        """
        return {
            'data': {
                'type': 'event',
                'attributes': {
                    'properties': {
                        'OrderId': event.order_id.name,
                        'Items': [
                            {
                                'ProductID': line.product_id.id,
                                'SKU': line.product_id.default_code,
                                'ProductName': line.product_id.name,
                                'Quantity': line.product_uom_qty,
                                'ItemPrice': line.price_unit,
                                'RowTotal': line.price_subtotal,
                                'ProductURL': line.product_id._get_item_url(),
                                'ImageURL': line.product_id.website_meta_og_img,
                            }
                            for line in event.order_id.order_line
                        ],
                        'BillingAddress': {
                            'FirstName': event.transaction_id.partner_name,
                            'Address1': event.transaction_id.partner_address or '',
                            'City': event.transaction_id.partner_state_id.name or '',
                            'RegionCode': event.transaction_id.partner_state_id.code or '',
                            'CountryCode': event.transaction_id.partner_country_id.code or '',
                            'zip': event.transaction_id.partner_zip or '',
                            'Phone': event.transaction_id.partner_phone or ''
                        },
                        'ShippingAddress': {
                            'Address1': event.order_id.partner_shipping_id.street
                        }
                    },
                    'time': event.transaction_id.last_state_change.strftime('%Y-%m-%dT%H:%M:%S'),
                    'value': event.transaction_id.amount,
                    'value_currency': event.transaction_id.currency_id.name,
                    'unique_id': f'transaction_{event.transaction_id.id}',
                    'metric': {
                        'data': {
                            'type': 'metric',
                            'attributes': {
                                'name': 'Placed Order'
                            }
                        }
                    },
                    'profile': {
                        'data': {
                            'type': 'profile',
                            'attributes': {
                                'email': event.transaction_id.partner_email
                            }
                        }
                    }
                }
            }
        }
