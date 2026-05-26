.. image:: https://img.shields.io/badge/licence-LGPL--3-green.svg
    :target: https://www.gnu.org/licenses/lgpl-3.0-standalone.html
    :alt: License: LGPL-3

Why Klaviyo?
============
With Klaviyo’s intelligent marketing automation software, you can automate personalized content with your data—without pressing send—and get a complete view of every customer. For example, build cross-channel experiences with email, SMS, and push notifications in the same flow—with consolidated reports in one place.

Learn more in Platform overview Learn how to: `<https://www.klaviyo.com/marketing-automation>`__.

Integration components
-------

* Customer data:

  * Tracking information such as name, email, and other profile attributes.

* Website activity:

  * Active on Site: When someone visits your website.
  
  * Viewed Product: When someone views a product.
  
  * Added to Cart: When someone adds an item to their cart.
  
  * Started Checkout: When someone lands on the checkout page.

* Order activity:

  * Placed Order: When an order is successfully processed in your system, tracking amount, products, etc.

Module it depends on:

* Odoo - Klaviyo Private API Keys `<https://apps.odoo.com/apps/modules/18.0/fpg_odoo_klaviyo_key>`__.

Configuration
-------
1. Setup the public API key, also called Site ID, to track Website activity:

  * Login to your Klaviyo.com account to copy the public API key. Follow the steps in How to manage your account's API keys: `<https://help.klaviyo.com/hc/en-us/articles/115005062267>`__.
  
  * Go to General Settings, Website, enable the Klaviyo option, and set the public API key.

2. Setup the private API key to track the Place Order action. The access level should include the Events with Read/Write Access:

  * Follow the steps in Odoo - Klaviyo Private API Keys `<https://apps.odoo.com/apps/modules/18.0/fpg_odoo_klaviyo_key>`__.

Check the operations:
-------
* Login to your Klaviyo.com and go to the Profile listing. Check if the Profile update datetime column is updated in profiles with recent activity.

* Select the profile to check its activity on the Website.

* You can also test and verify access and activity of Placed Order in the Odoo General Settings, Klaviyo section.
  Click on the Test Connection button to validate the private API key Events access level.
  Click on Open Logs link to check the status of the Placed Order actions:

  * Sent: The action was sent to Klaviyo successfully.
  
  * Wating: The action is waiting to be sent to Klaviyo.
  
  * Cancelled: After 3 failed attempts, the action will not be attempted to be sent to Klaviyo. You can open the log record to check the reason of the failure.

License
-------
General Public License, Version 3 (LGPL v3).
(https://www.gnu.org/licenses/lgpl-3.0-standalone.html)

Contacts
--------
Mail Contact : odooapps24@gmail.com

Further information
===================
HTML Description: `<static/description/index.html>`__