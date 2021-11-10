# -*- coding: utf-8 -*-

import odoo

__version__ = odoo.release.version

if __version__ == '10.0':
	import payment
else:
	from . import payment

