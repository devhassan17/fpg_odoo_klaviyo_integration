# -*- coding: utf-8 -*-

import ast
import json
import logging
import requests

from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError

from odoo import api, fields, models

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
        'res.partner',
        string='Customer',
        compute='_compute_partner_id',
        store=True
    )
    event_type = fields.Selection(
        selection=[
            ('placed_order', 'Placed Order'),
            ('started_checkout', 'Started Checkout'),
        ],
        string='Event Type',
        required=True,
        default='placed_order'
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

    @api.depends('transaction_id.partner_id', 'order_id.partner_id')
    def _compute_partner_id(self):
        for record in self:
            record.partner_id = record.transaction_id.partner_id or record.order_id.partner_id

    @api.model_create_multi
    def create(self, vals_list):
        filtered_vals_list = []
        for vals in vals_list:
            company = False
            if 'order_id' in vals and vals['order_id']:
                order = self.env['sale.order'].browse(vals['order_id'])
                company = order.company_id
            elif 'transaction_id' in vals and vals['transaction_id']:
                tx = self.env['payment.transaction'].browse(vals['transaction_id'])
                company = tx.company_id
            
            if self.env['res.config.settings'].check_klaviyo_company(company):
                filtered_vals_list.append(vals)
        
        if not filtered_vals_list:
            return self.env['fpg.odoo.klaviyo.integration.event.queue']
        return super(KlaviyoEventQueue, self).create(filtered_vals_list)

    def send_event(self):
        """Send Klaviyo Event to achieve Customer Lifetime Value (CLV)
        """
        # Start Event Processing
        api_key = self._get_klaviyo_api_key()
        if not api_key:
            return
        # Send events
        for event in self.search([('state', '=', 'waiting')]):
            event_company = event.order_id.company_id or (event.transaction_id.company_id if event.transaction_id else False)
            if not self.env['res.config.settings'].check_klaviyo_company(event_company):
                continue
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
                
                # Send Ordered Product events for Placed Order
                if event.event_type == 'placed_order':
                    try:
                        self._send_ordered_product_events(event, api_key)
                    except Exception as e:
                        _logger.exception("Klaviyo: Failed to send Ordered Product events: %s", e)
            else:
                try:
                    data.update({
                        'message': f'{response.status_code}:{json.dumps(response.json().get("errors"))}'
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
        partner = event.partner_id or event.order_id.partner_id
        
        # Build Profile Attributes
        profile_attrs = {
            'email': partner.email or (event.transaction_id.partner_email if event.transaction_id else ''),
        }
        if partner:
            if partner.x_first_name:
                profile_attrs['first_name'] = partner.x_first_name
            if partner.x_last_name:
                profile_attrs['last_name'] = partner.x_last_name
            elif partner.name and not partner.x_first_name:
                profile_attrs['first_name'] = partner.name
            
            phone = partner.phone or partner.mobile
            if phone:
                profile_attrs['phone_number'] = phone
                
            location = {}
            if partner.street:
                location['address1'] = partner.street
            if partner.street2:
                location['address2'] = partner.street2
            if partner.city:
                location['city'] = partner.city
            if partner.zip:
                location['zip'] = partner.zip
            if partner.country_id:
                location['country'] = partner.country_id.name or partner.country_id.code or ''
            if partner.state_id:
                location['region'] = partner.state_id.name or partner.state_id.code or ''
            if location:
                profile_attrs['location'] = location

        # Items details
        item_names = []
        categories = set()
        items_list = []
        for line in event.order_id.order_line:
            if line.product_id:
                item_names.append(line.product_id.name)
                cats = line.product_id.public_categ_ids.mapped('name') or [line.product_id.categ_id.name]
                for c in cats:
                    if c:
                        categories.add(c)
                items_list.append({
                    'ProductID': line.product_id.id,
                    'SKU': line.product_id.default_code or '',
                    'ProductName': line.product_id.name,
                    'Quantity': line.product_uom_qty,
                    'ItemPrice': line.price_unit,
                    'RowTotal': line.price_subtotal,
                    'ProductURL': line.product_id._get_item_url() or '',
                    'ImageURL': line.product_id.website_meta_og_img or '',
                })

        # Addresses
        if event.event_type == 'placed_order' and event.transaction_id:
            billing_address = {
                'FirstName': event.transaction_id.partner_name,
                'Address1': event.transaction_id.partner_address or '',
                'City': event.transaction_id.partner_state_id.name or '',
                'RegionCode': event.transaction_id.partner_state_id.code or '',
                'CountryCode': event.transaction_id.partner_country_id.code or '',
                'zip': event.transaction_id.partner_zip or '',
                'Phone': event.transaction_id.partner_phone or ''
            }
            shipping_address = {
                'Address1': event.order_id.partner_shipping_id.street or ''
            }
        else:
            billing_partner = event.order_id.partner_invoice_id or partner
            shipping_partner = event.order_id.partner_shipping_id or partner
            billing_address = {
                'FirstName': billing_partner.name or '',
                'Address1': billing_partner.street or '',
                'Address2': billing_partner.street2 or '',
                'City': billing_partner.city or '',
                'RegionCode': billing_partner.state_id.code or '',
                'CountryCode': billing_partner.country_id.code or '',
                'zip': billing_partner.zip or '',
                'Phone': billing_partner.phone or billing_partner.mobile or ''
            }
            shipping_address = {
                'Address1': shipping_partner.street or '',
                'Address2': shipping_partner.street2 or '',
                'City': shipping_partner.city or '',
                'RegionCode': shipping_partner.state_id.code or '',
                'CountryCode': shipping_partner.country_id.code or '',
                'zip': shipping_partner.zip or ''
            }

        # Event values
        if event.event_type == 'placed_order':
            value = event.transaction_id.amount if event.transaction_id else event.order_id.amount_total
            currency = event.transaction_id.currency_id.name if event.transaction_id else event.order_id.currency_id.name
            time_str = event.transaction_id.last_state_change.strftime('%Y-%m-%dT%H:%M:%S') if event.transaction_id and event.transaction_id.last_state_change else event.create_date.strftime('%Y-%m-%dT%H:%M:%S')
            unique_id = f'transaction_{event.transaction_id.id}' if event.transaction_id else f'placed_{event.order_id.id}'
            metric_name = 'Placed Order'
        else:
            value = event.order_id.amount_total
            currency = event.order_id.currency_id.name
            time_str = event.create_date.strftime('%Y-%m-%dT%H:%M:%S')
            unique_id = f'checkout_{event.order_id.id}'
            metric_name = 'Started Checkout'

        return {
            'data': {
                'type': 'event',
                'attributes': {
                    'properties': {
                        'OrderId': event.order_id.name,
                        'Items': items_list,
                        'ItemNames': item_names,
                        'Categories': list(categories),
                        'BillingAddress': billing_address,
                        'ShippingAddress': shipping_address
                    },
                    'time': time_str,
                    'value': value,
                    'value_currency': currency,
                    'unique_id': unique_id,
                    'metric': {
                        'data': {
                            'type': 'metric',
                            'attributes': {
                                'name': metric_name
                            }
                        }
                    },
                    'profile': {
                        'data': {
                            'type': 'profile',
                            'attributes': profile_attrs
                        }
                    }
                }
            }
        }

    def _send_ordered_product_events(self, event, api_key):
        """Send a separate 'Ordered Product' event to Klaviyo for each item in the order.
        """
        partner = event.partner_id or event.order_id.partner_id
        
        # Build Profile Attributes
        profile_attrs = {
            'email': partner.email or (event.transaction_id.partner_email if event.transaction_id else ''),
        }
        if partner:
            if partner.x_first_name:
                profile_attrs['first_name'] = partner.x_first_name
            if partner.x_last_name:
                profile_attrs['last_name'] = partner.x_last_name
            elif partner.name and not partner.x_first_name:
                profile_attrs['first_name'] = partner.name
            
            phone = partner.phone or partner.mobile
            if phone:
                profile_attrs['phone_number'] = phone
                
            location = {}
            if partner.street:
                location['address1'] = partner.street
            if partner.street2:
                location['address2'] = partner.street2
            if partner.city:
                location['city'] = partner.city
            if partner.zip:
                location['zip'] = partner.zip
            if partner.country_id:
                location['country'] = partner.country_id.name or partner.country_id.code or ''
            if partner.state_id:
                location['region'] = partner.state_id.name or partner.state_id.code or ''
            if location:
                profile_attrs['location'] = location

        time_str = event.transaction_id.last_state_change.strftime('%Y-%m-%dT%H:%M:%S') if event.transaction_id and event.transaction_id.last_state_change else event.create_date.strftime('%Y-%m-%dT%H:%M:%S')
        currency = event.transaction_id.currency_id.name if event.transaction_id else event.order_id.currency_id.name

        for line in event.order_id.order_line:
            if line.product_id:
                product = line.product_id
                categories = product.public_categ_ids.mapped('name') or [product.categ_id.name]
                
                payload = {
                    'data': {
                        'type': 'event',
                        'attributes': {
                            'properties': {
                                'OrderId': event.order_id.name,
                                'ProductID': product.id,
                                'SKU': product.default_code or '',
                                'ProductName': product.name,
                                'Quantity': line.product_uom_qty,
                                'ItemPrice': line.price_unit,
                                'RowTotal': line.price_subtotal,
                                'ProductURL': product._get_item_url() or '',
                                'ImageURL': product.website_meta_og_img or '',
                                'Categories': categories
                            },
                            'time': time_str,
                            'value': line.price_subtotal,
                            'value_currency': currency,
                            'unique_id': f'ordered_product_{event.order_id.id}_{line.id}',
                            'metric': {
                                'data': {
                                    'type': 'metric',
                                    'attributes': {
                                        'name': 'Ordered Product'
                                    }
                                }
                            },
                            'profile': {
                                'data': {
                                    'type': 'profile',
                                    'attributes': profile_attrs
                                }
                            }
                        }
                    }
                }
                
                try:
                    response = requests.post(
                        url=KLAVIYO_URL,
                        json=payload,
                        headers=ast.literal_eval(KLAVIYO_HEADERS % (api_key,)),
                        timeout=5
                    )
                    _logger.info("Klaviyo: Sent Ordered Product event for line %s (status: %s)", line.id, response.status_code)
                except Exception as e:
                    _logger.exception("Klaviyo: Failed to send Ordered Product event for line %s", line.id)
