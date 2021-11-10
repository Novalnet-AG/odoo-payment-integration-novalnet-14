# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


import odoo

__version__ = odoo.release.version

if __version__ == '10.0':
    import models
    import controllers
else:
    from . import models
    from . import controllers
    from odoo.addons.payment.models.payment_acquirer import create_missing_journal_for_acquirers

