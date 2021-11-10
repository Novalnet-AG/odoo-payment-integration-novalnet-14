# -*- coding: utf-8 -*-

{
    'name': 'Novalnet Payment Acquirer',
    'category': 'Payment',
    'summary': 'Payment Acquirer: Novalnet',
    'version': '2.0.0',
    'author': 'Novalnet',
    'website': 'http://www.novalnet.com',
    'description': """PCI Compliant, seamless integration with the various types of payment and payment-related services integrated into one unique platform. Please contact us at sales@novalnet.de""",
    'depends': ['payment'],
    'data': [
        'views/payment_views.xml',
        'views/payment_novalnet_templates.xml',
        'views/novalnet.xml',
        'data/payment_acquirer_data.xml',
    ],
    'installable': True,
}
