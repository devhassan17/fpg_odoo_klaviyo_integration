# -*- coding: utf-8 -*-

import logging
import re

from odoo import http
from odoo.http import request
from odoo.addons.odoo_uk_checkout_custom.controllers.main import WebsiteSaleCustom

_logger = logging.getLogger(__name__)

# Basic email validation pattern
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


class KlaviyoCheckoutCapture(http.Controller):
    """JSON endpoint for early Klaviyo profile capture at checkout.

    This creates/updates a Klaviyo profile as soon as the customer enters
    their email address during the first checkout step, before they submit
    the full form. This enables abandoned checkout identification in Klaviyo.
    """

    @http.route('/shop/klaviyo/capture_email', type='jsonrpc', auth='public', website=True, sitemap=False)
    def klaviyo_capture_email(self, email=None, **kw):
        """Receive an email from the checkout form and immediately sync it to Klaviyo.

        This endpoint is called via AJAX when the customer fills in or changes
        the email field on the checkout address form. It must never raise an
        exception — checkout must continue normally regardless of Klaviyo status.

        Actions performed:
        1. Create/update the Klaviyo profile (profile-import API).
        2. Fire a "Started Checkout" event directly via Klaviyo Events API.
        3. Subscribe the email if the marketing opt-in checkbox is checked.

        :param str email: The customer's email address.
        :param dict kw: Optional extra fields (first_name, last_name, phone, marketing_opt_in).
        :returns: dict with 'success' key.
        """
        result = {'success': False}
        try:
            if not email or not isinstance(email, str):
                result['reason'] = 'No email provided'
                return result

            email = email.strip().lower()
            if not _EMAIL_RE.match(email):
                result['reason'] = 'Invalid email format'
                return result

            # Build optional profile data from any extra fields already available
            profile_data = {}
            first_name = (kw.get('first_name') or '').strip()
            last_name = (kw.get('last_name') or '').strip()
            phone = (kw.get('phone') or '').strip()

            if first_name:
                profile_data['first_name'] = first_name
            if last_name:
                profile_data['last_name'] = last_name
            if phone:
                profile_data['phone_number'] = phone

            # 1. Create/update Klaviyo profile
            success, detail = request.env['res.partner'].sudo()._klaviyo_import_profile(
                email=email,
                profile_data=profile_data or None,
            )
            result['success'] = success
            result['detail'] = detail

            # 2. Fire "Started Checkout" event directly via Klaviyo Events API
            #    We send directly (not via event queue) because the queue uses order.partner_id
            #    which is the public user for guests — the wrong email.
            try:
                order = request.website.sale_get_order()
                if order and order.order_line:
                    ev_success, ev_detail = request.env['res.partner'].sudo()._klaviyo_send_started_checkout(
                        email=email,
                        order=order,
                        profile_data=profile_data or None,
                    )
                    result['event'] = ev_detail
            except Exception as e:
                _logger.exception("Klaviyo Checkout Capture: Failed to send Started Checkout event: %s", e)

            # 3. Subscribe email if marketing opt-in checkbox is checked
            marketing_opt_in = kw.get('marketing_opt_in')
            if marketing_opt_in:
                try:
                    sub_success, sub_detail = request.env['res.partner'].sudo()._klaviyo_subscribe_email(email)
                    result['subscribed'] = sub_success
                except Exception as e:
                    _logger.exception("Klaviyo Checkout Capture: Failed to subscribe %s: %s", email, e)

            return result

        except Exception as e:
            _logger.exception("Klaviyo Checkout Capture: Unexpected error for email '%s'", email)
            return {'success': False, 'reason': 'Internal error'}


class WebsiteSaleKlaviyo(WebsiteSaleCustom):
    """Extend the checkout address submission to update the Klaviyo profile
    with full customer details after the form is submitted.

    Since ``fpg_odoo_klaviyo_integration`` depends on ``odoo_uk_checkout_custom``,
    this override is architecturally clean — it extends the existing controller
    chain without modifying the parent module.
    """

    @http.route(['/shop/address/submit'], type='http', methods=['POST'], auth='public', website=True, sitemap=False)
    def shop_address_submit(self, **kw):
        # Let the full parent chain run first (standard Odoo + UK custom processing)
        response = super().shop_address_submit(**kw)

        # Now enrich the Klaviyo profile with all available checkout data
        try:
            email = (kw.get('email') or '').strip().lower()
            if email and _EMAIL_RE.match(email):
                profile_data = {}

                first_name = (kw.get('first_name') or '').strip()
                last_name = (kw.get('last_name') or '').strip()
                phone = (kw.get('phone') or '').strip()
                street = (kw.get('street') or '').strip()
                street2 = (kw.get('street2') or '').strip()
                city = (kw.get('city') or '').strip()
                zip_code = (kw.get('zip') or '').strip()

                if first_name:
                    profile_data['first_name'] = first_name
                if last_name:
                    profile_data['last_name'] = last_name
                if phone:
                    profile_data['phone_number'] = phone

                # Build location object if any address fields are present
                location = {}
                if street:
                    location['address1'] = street
                if street2:
                    location['address2'] = street2
                if city:
                    location['city'] = city
                if zip_code:
                    location['zip'] = zip_code

                # Resolve country name from country_id
                country_id = kw.get('country_id')
                if country_id:
                    try:
                        country = request.env['res.country'].sudo().browse(int(country_id))
                        if country.exists():
                            location['country'] = country.name
                    except (ValueError, TypeError):
                        pass

                # Resolve state/region from state_id
                state_id = kw.get('state_id')
                if state_id:
                    try:
                        state = request.env['res.country.state'].sudo().browse(int(state_id))
                        if state.exists():
                            location['region'] = state.name
                    except (ValueError, TypeError):
                        pass

                if location:
                    profile_data['location'] = location

                if profile_data:
                    request.env['res.partner'].sudo()._klaviyo_import_profile(
                        email=email,
                        profile_data=profile_data,
                    )
        except Exception as e:
            _logger.exception("Klaviyo Checkout: Failed to update profile on address submit: %s", e)

        return response
