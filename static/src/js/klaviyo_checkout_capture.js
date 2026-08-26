/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';

/**
 * Klaviyo Checkout Email Capture
 *
 * Captures the customer's email as soon as they enter it on the checkout
 * address form and immediately creates/updates a Klaviyo profile.
 *
 * This enables Klaviyo to identify customers who start checkout but abandon
 * before completing the form, even for guest/public users.
 *
 * The call is silent — if it fails, checkout continues normally.
 */
publicWidget.registry.KlaviyoCheckoutCapture = publicWidget.Widget.extend({
    selector: 'form[action*="/shop/address"]',

    events: {
        'change input[name="email"]': '_onEmailChange',
        'blur input[name="email"]': '_onEmailBlur',
    },

    /**
     * @override
     */
    start() {
        this._lastCapturedEmail = null;
        this._captureInProgress = false;
        return this._super(...arguments);
    },

    /**
     * Triggered when the email input value changes (e.g. autofill, paste).
     */
    _onEmailChange(ev) {
        this._captureEmail(ev.currentTarget);
    },

    /**
     * Triggered when the email field loses focus.
     * This is the primary trigger for most manual typing scenarios.
     */
    _onEmailBlur(ev) {
        this._captureEmail(ev.currentTarget);
    },

    /**
     * Core capture logic: validates the email, deduplicates, and sends
     * it to the server-side Klaviyo profile import endpoint.
     *
     * @param {HTMLInputElement} emailInput
     */
    async _captureEmail(emailInput) {
        const email = (emailInput.value || '').trim().toLowerCase();

        // Basic client-side validation
        if (!email || !this._isValidEmail(email)) {
            return;
        }

        // Dedup: don't re-send the same email
        if (email === this._lastCapturedEmail) {
            return;
        }

        // Prevent concurrent captures
        if (this._captureInProgress) {
            return;
        }

        this._captureInProgress = true;
        this._lastCapturedEmail = email;

        // Collect any other fields already filled in
        const params = { email: email };
        const firstName = (this.el.querySelector('#first_name, input[name="first_name"]')?.value || '').trim();
        const lastName = (this.el.querySelector('#last_name, input[name="last_name"]')?.value || '').trim();
        const phone = (this.el.querySelector('input[name="phone"]')?.value || '').trim();

        if (firstName) params.first_name = firstName;
        if (lastName) params.last_name = lastName;
        if (phone) params.phone = phone;

        try {
            // Server-side Klaviyo profile import via JSON-RPC
            await fetch('/shop/klaviyo/capture_email', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    params: params,
                }),
            });

            // Client-side Klaviyo identification (if klaviyo.js is loaded)
            if (window._learnq) {
                const identifyData = { email: email };
                if (firstName) identifyData['$first_name'] = firstName;
                if (lastName) identifyData['$last_name'] = lastName;
                if (phone) identifyData['$phone_number'] = phone;
                window._learnq.push(['identify', identifyData]);
            }
        } catch (err) {
            // Silent failure — do not disrupt checkout
            console.warn('Klaviyo email capture failed (non-blocking):', err);
        } finally {
            this._captureInProgress = false;
        }
    },

    /**
     * Basic email format validation.
     *
     * @param {string} email
     * @returns {boolean}
     */
    _isValidEmail(email) {
        return /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(email);
    },
});
