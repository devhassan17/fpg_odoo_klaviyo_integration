# -*- coding: utf-8 -*-
{
    'name': 'Odoo Klaviyo Integration',
    'summary': 'Odoo Klaviyo Integration',
    'description': 'Odoo eCommerce Integration with Klaviyo.',
    'author': 'FPG',
    'category': 'Marketing',
    'version': '19.0.1.1.15',
    'depends': [
        'website_sale',
        'fpg_odoo_klaviyo_key',
        'odoo_uk_checkout_custom'
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/klaviyo_event_queue_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/snippets_template.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'images': [
        'static/description/main_screenshot.png'
    ],
    'price': 122.95,
    'currency': 'USD',
}
