# coding: utf-8

import base64
import binascii
import hashlib
import logging
import socket
import random
import re
import odoo

from werkzeug import urls
from collections import OrderedDict
from odoo.tools import html_escape
from random import randint
from odoo import api, fields, models, tools, _
from datetime import datetime, timedelta
from openerp.exceptions import Warning
from openerp.tools import float_round, DEFAULT_SERVER_DATE_FORMAT

from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment_novalnet.controllers.main import NovalnetController
from odoo.http import request
from collections import Counter
from platform import python_version
from Crypto.Cipher import AES
try:
    # Python 2.6-2.7 
    from HTMLParser import HTMLParser
except ImportError:
    # Python 3
    import html.parser

_pad = lambda s: s + (16 - len(s) % 16) * chr(16 - len(s) % 16)
_unpad = lambda s : s[:-ord(s[len(s)-1:])]
_logger = logging.getLogger(__name__)
__version__ = odoo.release.version
class NovalnetTable(models.Model):

    """ Creating Novalnet custom tables """
    _name = 'novalnet.table'

    """ Overriding the table structure """
    _auto = False

    """ Custom table structure
    >>> init(cr)
    """
    def init(self):

        """ Novalnet Callback table """
        self._cr.execute("""
            CREATE TABLE IF NOT EXISTS novalnet_callback (
            id serial NOT NULL PRIMARY KEY,
            order_no varchar(20) NOT NULL,
            callback_amount integer NOT NULL,
            total_amount integer NOT NULL,
            reference_tid bigint,
            callback_tid bigint,
            callback_log text,
            gateway_status integer NOT NULL,
            additional_info text,
            payment_method_type text);
        """)

        """ Novalnet Affiliate table """
        self._cr.execute("""
            CREATE TABLE IF NOT EXISTS novalnet_aff_account_detail (
            id serial NOT NULL PRIMARY KEY,
            vendor_id integer NOT NULL,
            vendor_authcode varchar(50) NOT NULL,
            product_id integer NOT NULL,
            product_url varchar(100) NOT NULL,
            aff_id integer NOT NULL,
            aff_authcode varchar(50) NOT NULL,
            aff_accesskey varchar(50) NOT NULL);
        """)

class AcquirerNovalnet(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[('novalnet', 'Novalnet')])
    novalnet_test_mode = fields.Boolean(_('Enable Test Mode'), default=False, help=_('The payment will be processed in the test mode therefore amount for this transaction will not be charged'))
    novalnet_vendor = fields.Char(_('Merchant ID'), help=_('Enter Novalnet merchant ID'))
    novalnet_auth_code = fields.Char(_('Authentication code'), help=_('Enter Novalnet authentication code'))
    novalnet_product = fields.Char(_('Project ID'), help=_('Enter Novalnet project ID'))
    novalnet_tariff = fields.Char(_('Tariff ID'), help=_('Enter Novalnet tariff ID'))
    novalnet_access_key = fields.Char(_('Payment access key'), help=_('Enter the Novalnet payment access key'))
    novalnet_cc_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_sepa_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_invoice_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_prepayment_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_cashpayment_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_paypal_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_przelewy24_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_sofort_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_ideal_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_eps_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_giropay_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_on_hold_confirmation_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Onhold order status'),default='done')
    novalnet_on_hold_cancellation_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Cancellation order status'),default='cancel')
    novalnet_invoice_callback_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Callback order status'),default='done')
    novalnet_prepayment_callback_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Callback order status'),default='done')
    novalnet_cashpayment_callback_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Callback order status'),default='done')
    paypal_payment_pending_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order status for the pending payment'), default='pending')
    przelewy24_payment_pending_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order status for the pending payment'), default='pending')
    novalnet_manual_check_limit = fields.Selection([('capture',_('Capture')),('authorize',_('Authorize'))],_('Payment action'), default='capture')
    novalnet_manual_check_limit_amount = fields.Char(_('Minimum transaction limit for authorization(in minimum unit of currency. E.g. enter 100 which is equal to 1.00)'), help=_('In case the order amount exceeds the mentioned limit, the transaction will be set on-hold till your confirmation of the transaction. You can leave the field empty if you wish to process all the transactions as on-hold.'))
    novalnet_enable_cc3d = fields.Boolean(_('Enable 3D secure'), default=False, help=_('The 3D-Secure will be activated for credit cards. The issuing bank prompts the buyer for a password what, in turn, help to prevent a fraudulent payment. It can be used by the issuing bank as evidence that the buyer is indeed their card holder. This is intended to help decrease a risk of charge-back.'))    
    novalnet_sepa_due_date = fields.Char(_('SEPA payment duration (in days)'), help=_('Enter the number of days after which the payment should be processed (must be greater than 6 days)'))
    novalnet_invoice_due_date = fields.Char(_('Payment due date (in days)'), help=_('Enter the number of days to transfer the payment amount to Novalnet (must be greater than 7 days). In case if the field is empty, 14 days will be set as due date by default'))
    novalnet_cashpayment_slip_expiry_date = fields.Char(_('Slip expiry date (in days)'), help=_('Enter the number of days to pay the amount at store near you. If the field is empty, 14 days will be set as default.'))
    novalnet_referrer_id = fields.Char(_('Referrer ID'), help=_('Enter the referrer ID of the person/company who recommended you Novalnet'))
    novalnet_callbackscript_test_mode = fields.Boolean(_('Deactivate IP address control (for test purpose only)'),default=False,help=_('This option will allow performing a manual execution. Please disable this option before setting your shop to LIVE mode, to avoid unauthorized calls from external parties (excl. Novalnet).'))
    novalnet_callbackscript_email = fields.Boolean(_('Enable E-mail notification for callback'),default=False)
    novalnet_callbackscript_email_from = fields.Char(_('E-mail address (From)'), help=_('E-mail address of the sender'))
    novalnet_callbackscript_email_to = fields.Char(_('E-mail address (To)'), help=_('E-mail address of the recipient'))
    novalnet_callbackscript_email_bcc = fields.Char(_('E-mail address (Bcc)'), help=_('E-mail address of the recipient for BCC'))
    novalnet_callbackscript_notify_url = fields.Char(_('Notification URL'), default='http://localhost:8069/payment/novalnet/callback/?db=<db_name>', help=_('The notification URL is used to keep your database/system actual and synchronizes with the Novalnet transaction status.'))

    """ Implements encryption that is compatible with openssl AES-256 CBC mode
    """
    def _generate_encode(self,encode_value,access_key,unique_id ):
            html_parser = self._get_html_parser()
            encode_value = _pad(encode_value)
            cipher = AES.new(access_key, AES.MODE_CBC, unique_id)
            if html_parser == None:
               return base64.b64encode(cipher.encrypt(encode_value))
            else:
                return html_parser.unescape(base64.b64encode(cipher.encrypt(encode_value)))


    def _get_html_parser(self):
        try:
            if python_version() < '3.0.0':
               return HTMLParser()
        except ValueError:
            return None

    """ Returns encoded values
    """
    def _encode_data(self, encode_values, access_key,unique_id):
        for key, value in encode_values.items():
            encode_values[key] = self._generate_encode(encode_values[key], access_key, unique_id)
        return encode_values


    """ Generating hash for the encoded values
    >>> self._generate_hashing(_values, _access_key)
    string
    """
    def _generate_hash(self, values, _access_key,uniqid):
        auth_code = repr(str(values['auth_code']))[3:-2]
        product = repr(str(values['product']))[3:-2]
        tariff = repr(str(values['tariff']))[3:-2]
        amount = repr(str(values['amount']))[3:-2]
        test_mode = repr(str(values['test_mode']))[3:-2]
        data = ''.join([ auth_code, product, tariff, amount, test_mode, str(uniqid), _access_key[::-1]])
        return hashlib.sha256(data.encode('utf-8')).hexdigest()           

    """ Core function to form hidden values
    >>> %s_form_generate_values(_values)
    array
    """
    
    def novalnet_form_generate_values(self, _values):
        _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        _remote_address = self.get_client_ip()
        _server_address = socket.gethostbyname(socket.gethostname())
        _order_amount = float(_values['amount']) *100

        """ Formatting Order amount to cents """
        _order_formated_amount = '%g' % _order_amount

        """ Initiate the parameters """
        _transaction_values = {
            'gender'             : 'u',
            'amount'             : _order_formated_amount,
            'test_mode'          : '1' if self.novalnet_test_mode else '0',
            'system_name'        : 'odoo'+__version__,
            'system_version'     : __version__+'-NN2.1.0',
            'system_ip'          : _server_address,
            'system_url'         : '%s' % urls.url_join(_base_url, ''),
            'address_form'       : '0',
            'thide'              : '1',
            'shide'              : '1',
            'lhide'              : '1',
            'hfooter'            : '0',
            'skip_cfm'           : '1',
            'lang'               : 'de' if _values['partner_lang'] == 'de_DE' else 'en',
            'language'           : 'de' if _values['partner_lang'] == 'de_DE' else 'en',
            'reference'          : _values['reference'],
            'remote_ip'          : _remote_address,
            'return_url'         : '%s' % urls.url_join(_base_url, NovalnetController._return_url),
            'error_return_url'   : '%s' % urls.url_join(_base_url, NovalnetController._return_url),
            'return_method'      : 'POST',
            'error_return_method': 'POST',
            'currency'           : _values['currency'].name,
            'street'             : _values.get('billing_partner_address'),
            'search_in_street'   : '1',
            'city'               : _values.get('billing_partner_city'),
            'country_code'       : _values.get('billing_partner_country').code,
            'email'              : _values.get('billing_partner_email'),
            'zip_code'           : _values.get('billing_partner_zip'),
            'implementation'     : 'ENC',
            'first_name'         : _values.get('billing_partner_first_name') if _values.get('billing_partner_first_name') != '' else _values.get('billing_partner_last_name'),
            'last_name'          : _values.get('billing_partner_last_name') if _values.get('billing_partner_last_name') != '' else values.get('billing_partner_first_name'),
            'tel'                : _values.get('billing_partner_phone'),
        }

        """ Show testmode description """
        _transaction_values['show_test_mode'] = True if _transaction_values['test_mode'] == '1' else False

        """ Check for Notify URL """
        if self.novalnet_callbackscript_notify_url != False:
            _transaction_values['notify_url'] = self.novalnet_callbackscript_notify_url

        """ Check for referrer ID """
        if self.novalnet_referrer_id > '0':
            _transaction_values['referrer_id'] = self.novalnet_referrer_id

        """ Check for company """
        if _values.get('billing_partner_company'):
            _transaction_values['company'] = _values.get('billing_partner_company')

        """ Check for On-Hold """
        _get_manual_check_limit_amount = self._is_valid_digit(self.novalnet_manual_check_limit_amount)
        if (self.novalnet_manual_check_limit == 'authorize'  and  not _get_manual_check_limit_amount)  or (self.novalnet_manual_check_limit == 'authorize'  and _get_manual_check_limit_amount and self._is_valid_digit(_transaction_values['amount']) >= _get_manual_check_limit_amount):
            _transaction_values['on_hold'] = 1

        """ Check for Credit card 3d """
        if self.novalnet_enable_cc3d:
            _transaction_values['novalnet_cc_3d'] = 1

        return self._parameters_validation(_transaction_values)

    """" get client ip address    
    """
    def get_client_ip(self):
        if request.httprequest.headers.environ.get("HTTP_X_REAL_IP") != None and request.httprequest.headers.environ.get("HTTP_X_REAL_IP") != '':
            return request.httprequest.headers.environ.get("HTTP_X_REAL_IP")
        elif request.httprequest.headers.environ.get("HTTP_X_FORWARDED_FOR") != None and request.httprequest.headers.environ.get("HTTP_X_FORWARDED_FOR") != '':
            return request.httprequest.headers.environ.get("HTTP_X_FORWARDED_FOR")
        elif request.httprequest.headers.environ.get("REMOTE_ADDR") != None and request.httprequest.headers.environ.get("REMOTE_ADDR") != '':
            return request.httprequest.headers.environ.get("REMOTE_ADDR")
        else:
            return ''


    """ Process validation and Novalnet
    configuartion parameters formation
    >>> self._parameters_validation(_transaction_values)
    array
    """
    def _parameters_validation(self, _transaction_values):

        """ strip the value to remove space """
        _access_key       = self._strip_remove_space(self.novalnet_access_key)
        _auth_code        = self._strip_remove_space(self.novalnet_auth_code)
        _product          = self._strip_remove_space(self.novalnet_product)
        _tariff           = self._strip_remove_space(self.novalnet_tariff)
        _vendor           = self._strip_remove_space(self.novalnet_vendor)
        _invoice_due_date = self._is_valid_digit(self._strip_remove_space(self.novalnet_invoice_due_date))
        _cashpayment_slip_expiry_date = self._is_valid_digit(self._strip_remove_space(self.novalnet_cashpayment_slip_expiry_date))
        _sepa_due_date    = self._is_valid_digit(self._strip_remove_space(self.novalnet_sepa_due_date))
        _transaction_values['vendor']    = _vendor
        """ Basic parameters validation """
        if not _access_key or not _auth_code or not self._is_valid_digit(_product) or not self._is_valid_digit(_tariff) or not self._is_valid_digit(_vendor):
            _transaction_values ['novalnet_validation_message'] = _('Basic parameter not valid')
            return _transaction_values

        """ Due date validations """
        
        if _sepa_due_date and _sepa_due_date >=2 and _sepa_due_date <=14: 
            _transaction_values['sepa_due_date'] = _sepa_due_date 
        
        if _invoice_due_date  and _invoice_due_date >=7:
            _transaction_values['due_date'] = _invoice_due_date                 
        
        if _cashpayment_slip_expiry_date:
            _transaction_values['cp_due_date'] = _cashpayment_slip_expiry_date
        
        """Forming encoded values """
        encode_values = {"product": _product,"auth_code": _auth_code, 'tariff':_tariff,'amount':_transaction_values['amount'],'test_mode':_transaction_values['test_mode'] }
        unique_id = str(int(random.random()*10000000000000000))
        encode_details= self._encode_data(encode_values, _access_key,unique_id)
        _transaction_values = _transaction_values.copy()
        _transaction_values.update(encode_details)
        _transaction_values['uniqid'] = unique_id
        _transaction_values['hash'] = self._generate_hash(encode_details, _access_key,unique_id)
        return _transaction_values

    def _strip_remove_space(self, _data):
        return _data.strip() if _data else False

    """ Core function to append form
    action URL
    >>> %s_get_form_action_url()
    string
    """
    
    def novalnet_get_form_action_url(self):
        return 'https://paygate.novalnet.de/paygate.jsp'

    """ Check for integer
    >>> _is_valid_digit(value)
    """
    def _is_valid_digit(self, _value):
        try:
            return int(_value)
        except ValueError:
            return False

class TxNovalnet(models.Model):
    """ This class inherits the payment.transaction class which
    process the response from the server and update details in
    the corresponding order
    """
    _inherit = 'payment.transaction'

    """ Core function to get
    order details
    >>> %s_form_get_transaction_from_data(_data)
    Boolean
    """
    @api.model
    def _novalnet_form_get_tx_from_data(self, _data):

        """ Search for the  order details using the order_no from the response """
        return self.search([('reference', '=', _data.get('order_no'))])

    """ Core function to get
    order details
    >>> %s_form_validate(transaction, data)
    string
    """
    @api.model
    def _novalnet_form_validate(self, data):
        if self.acquirer_reference != False:
            _logger.warning('Order status already processed with the tid : %s' % self.acquirer_reference)
            return True

        """ Convert status int integer to use further """
        _status_code = int(data.get('status', '0'))
        _tid_status_code = int(data.get('tid_status', '0'))

        _payment_key = data.get('payment_id') if data.get('key') != '6' and data.get('key') == None else data.get('key')
        _payment_property = self._get_payment_method(_payment_key)

        """ Get Novalnet configuration details """
        _payment_acquirer = self.acquirer_id

        _test_mode = self._decode(data.get('test_mode'),_payment_acquirer.novalnet_access_key,data.get('uniqid'))

        """ Check for test mode """
        _test_mode = '1' if _payment_acquirer.novalnet_test_mode or _test_mode != '0' else '0'

        """ Forming basic comments """
        if data.get('payment_id') == '27':
            if data.get('invoice_type') == 'INVOICE':
               _comments = self._form_basic_comments(_('Invoice'), data.get('tid'), data.get('payment_id'),_test_mode, data.get('tid_status'))
            elif data.get('invoice_type') == 'PREPAYMENT':
               _comments = self._form_basic_comments(_('Prepayment'), data.get('tid'), data.get('payment_id'),_test_mode, data.get('tid_status'))
        elif data.get('payment_id') == '40' and data.get('tid_status') in ['75','99']:
            _comments = self._form_basic_comments('Novalnet Direct Debit SEPA', data.get('tid'), data.get('payment_id'),_test_mode, data.get('tid_status'))
        elif data.get('payment_id') == '41' and data.get('tid_status') in ['75','91']:
            _comments = self._form_basic_comments('Invoice', data.get('tid'), data.get('payment_id'),_test_mode, data.get('tid_status'))
        else:
            _comments = self._form_basic_comments(_payment_property['payment_name'], data.get('tid'), data.get('payment_id'),_test_mode, data.get('tid_status'))

        """ Get Novalnet response message """
        _response_message = self._get_status_message(data)
        _logger.info(_response_message)

        _orginal_order_no = self.reference.split('-')

        _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        _url = '%s' % urls.url_join(_base_url, '')

        _order_amount =  self._decode(data.get('amount'),_payment_acquirer.novalnet_access_key,data.get('uniqid'))
        _amount = self._get_respons_amount(_order_amount)
        _server_amount = '%g' % _amount
        _additional_info = ''
        if data.get('hash2'):
            _unique_id = data.get('uniqid')
            _values = {'auth_code':data.get('auth_code'),'product':data.get('product'),'tariff':data.get('tariff'),'amount':data.get('amount'),'test_mode':data.get('test_mode')}
            _hash_result = self._generate_hash(_values, _payment_acquirer.novalnet_access_key, _unique_id)
            self.env['ir.config_parameter'].set_param('hash_result', _hash_result)
        
        if 'hash2' in data and data.get('hash2') == _hash_result:
            if _status_code == 100 or (_status_code == 90 and data.get('key') == '34'):
                """ Unset the cart session """
                request.session['sale_order_id'] = None
                
                _callback_amount = _server_amount
                _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
                _url = '%s' % urls.url_join(_base_url, '')

                if data.get('tid_status') == '86' and data.get('key') == '78':
                    _callback_amount = 0
                    _order_status = _payment_acquirer.przelewy24_payment_pending_status
                """ Paypal pending process """
                if data.get('tid_status') == '90' and data.get('key') == '34':
                    _callback_amount = 0
                    _order_status = _payment_acquirer.paypal_payment_pending_status
                if data.get('tid_status') == '85' and data.get('key') == '34':
                    _callback_amount = 0
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
     
                if data.get('tid_status') == '91':
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
                
                if data.get('tid_status') == '98':
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
                
                if data.get('tid_status') == '99':
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
                     
                """ Check for Cashpayment payment """
                if data.get('payment_id') == '59' and data.get('tid_status') == '100':
                    _callback_amount = 0
                    
                    """ Assign order completion status """
                    _order_status = _payment_acquirer.novalnet_cashpayment_order_completion_status
                    
                    _additional_info = data.get("cp_checkout_token")
                    _nearest_store =  self._get_nearest_store(data);
                    _nearest_store_count =  self._get_count_nearest_store(data);
                    _comments = _comments + _('Slip Expire date: %s')% data.get("cp_due_date")
                    if _nearest_store != '':
                        self.env.cr.execute("SELECT to_regclass('schema_name.res_country')")
                        _get_country = self.env.cr.fetchone()
                        _store_comments = ''
                        for _incremant_id in range(0,_nearest_store_count):
                                _incremant_id += 1
                                if _get_country:
                                   _country_name = self.env.cr.execute("select name from res_country where code = %s",(_nearest_store['nearest_store_country_'+str(_incremant_id)],))
                                   _country_name = self.env.cr.fetchone()
                                if _nearest_store['nearest_store_title_'+str(_incremant_id)] != '':
                                    _store_title_comments = '\n'+_nearest_store['nearest_store_title_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_street_'+str(_incremant_id)] != '':
                                    _store_street_comments = _nearest_store['nearest_store_street_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_city_'+str(_incremant_id)] != '':
                                    _store_city_comments = _nearest_store['nearest_store_city_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_zipcode_'+str(_incremant_id)] != '':
                                    _store_zipcode_comments = _nearest_store['nearest_store_zipcode_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_country_'+str(_incremant_id)] != '':
                                    _store_country_comments = _country_name[0]
                                _store_comments += _store_title_comments + '\n' + _store_street_comments + '\n' + _store_city_comments + '\n' + _store_zipcode_comments + '\n' +_store_country_comments
                        _comments = _comments + '\n' +_store_comments
                """ Check for invoice payment """
                if data.get('payment_id') == '27' and data.get('tid_status') == '100':
                    """ Assign callback_amount as zero for payment pending payments """
                    _callback_amount = 0

                    """ Assign order completion status """
                    _order_status = _payment_acquirer.novalnet_invoice_order_completion_status 

                    """ Check for invoice type """
                    _payment_property = self._invoice_type(data.get('invoice_type'))

                    """ Bank details array """
                    _invoice_details = {
                        'invoice_account_holder' : data.get('invoice_account_holder'),
                        'tid'                    : data.get('tid'),
                        'due_date'               : data.get('due_date'),
                        'invoice_iban'           : data.get('invoice_iban'),
                        'invoice_bic'            : data.get('invoice_bic'),
                        'invoice_bankname'       : data.get('invoice_bankname'),
                        'invoice_bankplace'      : data.get('invoice_bankplace'),
                        'amount'                 : data.get('amount'),
                        'currency'               : data.get('currency'),
                    }
                    """ Built comments with bank details """
                    if _tid_status_code in [100,91]:
                        _comments = _comments + self._form_bank_comments(_invoice_details, _payment_acquirer, self.reference)
                        
                if data.get('payment_id') == '6' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_cc_order_completion_status
                    
                if data.get('payment_id') == '37' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_sepa_order_completion_status
                    
                if data.get('payment_id') == '33' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_sofort_order_completion_status
                
                if data.get('payment_id') == '49' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_ideal_order_completion_status
                
                if data.get('payment_id') == '50' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_eps_order_completion_status
                
                if data.get('payment_id') == '69' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_giropay_order_completion_status
                
                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status, additional_info) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)', (data.get("order_no"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code ,_additional_info))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                self.env.cr.commit()

                """ Order updation """
                if __version__ in ['12.0','13.0']:
                    self._set_transaction_pending()
                return self.write({'state': _order_status,'acquirer_reference': data.get('tid'),'state_message': _comments})
                
            elif _status_code != '100' and 'tid' in data:
                _callback_amount = 0
                _tid_status_code = int(data.get('tid_status', '0'))
                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (data.get("order_no"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments+_response_message+'\n', _orginal_order_no[0]))
                self.env.cr.commit()

                """ Cancel the order on server validation """
                return self.write({
                    'state': 'cancel',
                    'state_message': _comments +_response_message+'\n',
                })
        
        elif 'hash2' not in data :
            if _status_code == 100 or (_status_code == 90 and data.get('key') == '34'):
                """ Unset the cart session """
                request.session['sale_order_id'] = None
                
                _callback_amount = _server_amount
                _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
                _url = '%s' % urls.url_join(_base_url, '')

                if data.get('tid_status') == '86' and data.get('key') == '78':
                    _callback_amount = 0
                    _order_status = _payment_acquirer.przelewy24_payment_pending_status
                """ Paypal pending process """
                if data.get('tid_status') == '90' and data.get('key') == '34':
                    _callback_amount = 0
                    _order_status = _payment_acquirer.paypal_payment_pending_status
                if data.get('tid_status') == '85' and data.get('key') == '34':
                    _callback_amount = 0
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
     
                if data.get('tid_status') == '91':
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
                
                if data.get('tid_status') == '98':
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
                
                if data.get('tid_status') == '99':
                    _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status
                     
                """ Check for Cashpayment payment """
                if data.get('payment_id') == '59' and data.get('tid_status') == '100':
                    _callback_amount = 0
                    
                    """ Assign order completion status """
                    _order_status = _payment_acquirer.novalnet_cashpayment_order_completion_status
                    
                    _additional_info = data.get("cp_checkout_token")
                    _nearest_store =  self._get_nearest_store(data);
                    _nearest_store_count =  self._get_count_nearest_store(data);
                    _comments = _comments + _('Slip Expire date: %s')% data.get("cp_due_date")
                    if _nearest_store != '':
                        self.env.cr.execute("SELECT to_regclass('schema_name.res_country')")
                        _get_country = self.env.cr.fetchone()
                        _store_comments = ''
                        for _incremant_id in range(0,_nearest_store_count):
                                _incremant_id += 1
                                if _get_country:
                                   _country_name = self.env.cr.execute("select name from res_country where code = %s",(_nearest_store['nearest_store_country_'+str(_incremant_id)],))
                                   _country_name = self.env.cr.fetchone()
                                if _nearest_store['nearest_store_title_'+str(_incremant_id)] != '':
                                    _store_title_comments = '\n'+_nearest_store['nearest_store_title_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_street_'+str(_incremant_id)] != '':
                                    _store_street_comments = _nearest_store['nearest_store_street_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_city_'+str(_incremant_id)] != '':
                                    _store_city_comments = _nearest_store['nearest_store_city_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_zipcode_'+str(_incremant_id)] != '':
                                    _store_zipcode_comments = _nearest_store['nearest_store_zipcode_'+str(_incremant_id)]
                                if _nearest_store['nearest_store_country_'+str(_incremant_id)] != '':
                                    _store_country_comments = _country_name[0]
                                _store_comments += _store_title_comments + '\n' + _store_street_comments + '\n' + _store_city_comments + '\n' + _store_zipcode_comments + '\n' +_store_country_comments
                        _comments = _comments + '\n' +_store_comments
                """ Check for invoice payment """
                if data.get('payment_id') == '27' and data.get('tid_status') == '100':
                    """ Assign callback_amount as zero for payment pending payments """
                    _callback_amount = 0

                    """ Assign order completion status """
                    _order_status = _payment_acquirer.novalnet_invoice_order_completion_status 

                    """ Check for invoice type """
                    _payment_property = self._invoice_type(data.get('invoice_type'))

                    """ Bank details array """
                    _invoice_details = {
                        'invoice_account_holder' : data.get('invoice_account_holder'),
                        'tid'                    : data.get('tid'),
                        'due_date'               : data.get('due_date'),
                        'invoice_iban'           : data.get('invoice_iban'),
                        'invoice_bic'            : data.get('invoice_bic'),
                        'invoice_bankname'       : data.get('invoice_bankname'),
                        'invoice_bankplace'      : data.get('invoice_bankplace'),
                        'amount'                 : data.get('amount'),
                        'currency'               : data.get('currency'),
                    }
                    """ Built comments with bank details """
                    if _tid_status_code in [100,91]:
                        _comments = _comments + self._form_bank_comments(_invoice_details, _payment_acquirer, self.reference)
                        
                if data.get('payment_id') == '6' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_cc_order_completion_status
                    
                if data.get('payment_id') == '37' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_sepa_order_completion_status
                    
                if data.get('payment_id') == '33' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_sofort_order_completion_status
                
                if data.get('payment_id') == '49' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_ideal_order_completion_status
                
                if data.get('payment_id') == '50' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_eps_order_completion_status
                
                if data.get('payment_id') == '69' and data.get('tid_status') == '100':
                    _order_status = _payment_acquirer.novalnet_giropay_order_completion_status
                
                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status, additional_info) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)', (data.get("order_no"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code ,_additional_info))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                self.env.cr.commit()

                """ Order updation """
                if __version__ in ['12.0','13.0']:
                    self._set_transaction_pending()
                return self.write({'state': _order_status,'acquirer_reference': data.get('tid'),'state_message': _comments})
                
            elif _status_code != '100' and 'tid' in data:
                _callback_amount = 0
                _tid_status_code = int(data.get('tid_status', '0'))
                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (data.get("order_no"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments+_response_message+'\n', _orginal_order_no[0]))
                self.env.cr.commit()

                """ Cancel the order on server validation """
                return self.write({
                    'state': 'cancel',
                    'state_message': _comments +_response_message+'\n',
                })
                   
        else:
            return self.write({
                    'state': 'draft'
                })

    def _get_count_nearest_store(self,response):
        _nearest_store_count = 0
        for key, value in response.items():
            if key.find('nearest_store_title') != -1:
               _nearest_store_count += 1
        return _nearest_store_count
    """
    """
    
    def _generate_hash(self, values, _access_key,uniqid):
        auth_code = values['auth_code']
        product = values['product']
        tariff = values['tariff']
        amount = values['amount']
        test_mode = values['test_mode']
        data = ''.join([ auth_code, product, tariff, amount, test_mode, str(uniqid), _access_key[::-1]])
        return hashlib.sha256(data.encode('utf-8')).hexdigest()
    
    def _get_nearest_store(self,_response):
        _stores = {}
        for key, value in _response.items():
            if key.find('nearest_store') != -1:
                _stores[key] = value;
        return _stores;
        
    """ To get payment property based on
    the payment key
    >>> _get_payment_method(_key)
    array
    """
    def _get_payment_method(self, _key):
        _payment_array = {
            '6'  : { 'payment_name': _('Credit Card'), 'payment_method_type': 'novalnet_cc' },
            '27' : { 'payment_name': _('Invoice'), 'payment_method_type': 'novalnet_invoice' },
            '27' : { 'payment_name': _('Prepayment'), 'payment_method_type': 'novalnet_prepayment' },
            '33' : { 'payment_name': _('Instant Bank Transfer'), 'payment_method_type': 'novalnet_instant_bank_transfer' },
            '34' : { 'payment_name': _('PayPal'), 'payment_method_type': 'novalnet_paypal' },
            '37' : { 'payment_name': _('Direct Debit SEPA'), 'payment_method_type': 'novalnet_sepa' },
            '40' : { 'payment_name': _('Direct Debit SEPA'), 'payment_method_type': 'novalnet_sepa' },
            '41' : { 'payment_name': _('Invoice'), 'payment_method_type': 'novalnet_invoice' },
            '49' : { 'payment_name': _('iDEAL'), 'payment_method_type': 'novalnet_ideal' },
            '50' : { 'payment_name': _('eps'), 'payment_method_type': 'novalnet_eps' },
            '59' : { 'payment_name': _('Cashpayment'), 'payment_method_type': 'novalnet_cashpayment' },
            '69' : { 'payment_name': _('giropay'), 'payment_method_type': 'novalnet_giropay' },
            '78' : { 'payment_name': _('Przelewy24'), 'payment_method_type': 'novalnet_przelewy24' },
            
            
        }

        """ Check whether key is present in the response or not """
        return _payment_array[_key] if _key != None else {'payment_name':'Novalnet','payment_method_type':'novalnet'}

    """ Get status message value
    from the Novalnet server
    >>> _get_status_message(_response)
    string
    """
    def _get_status_message(self, _response):
        return _response.get('status_desc') if _response.get('status_desc') != None else ( _response.get('status_text') if _response.get('status_text') != None else (_response.get('status_message') if _response.get('status_message') != None else 'Payment was not successful. An error occurred.' ))

    """ Generate basic comments
    >>> _form_basic_comments(_payment_name, _tid)
    string
    """
    def _form_basic_comments(self, _payment_name, _tid,_payment_id, _test_mode, tid_status):
        _comments = ''
        if _payment_id in ['40','41']:
            _comments = 'This is processed as a guarantee payment\n'
        _comments =  _comments + '\n'+_payment_name + _('\nNovalnet transaction ID: %s \n')% _tid + _('Test order\n') if _test_mode == '1' else '\n'+_payment_name + _('\nNovalnet transaction ID: %s \n')% _tid
        if _payment_id == '40' and tid_status == '75':
            _comments = _comments + 'Your order is under verification and we will soon update you with the order status. Please note that this may take upto 24 hours.'
        if _payment_id == '41' and tid_status == '75': 
            _comments = _comments + 'Your order is under verification and once confirmed, we will send you our bank details to where the order amount should be transferred. Please note that this may take upto 24 hours.'
        return _comments

    """ Generate Bank comments
    >>> _form_bank_comments(_invoice_details, _payment_acquirer, _order_no)
    string
    """
    def _form_bank_comments(self, _invoice_details, _payment_acquirer, _order_no,_callback = False):
        _amount = float( _invoice_details['amount'])/100.0 if _callback else float(_invoice_details['amount'])
        _amount_formated = ('%.2f' % _amount)
        _due_date = datetime.strptime(_invoice_details['due_date'], '%Y-%m-%d').strftime('%d.%m.%Y')
        _comments = _('Please transfer the amount to the below mentioned account details of our payment processor Novalnet')+'\n'+_('Due date: ')+ _due_date+'\n'+_('Account holder: ')+_invoice_details['invoice_account_holder']  +'\n' +_('IBAN: ')+ _invoice_details.get("invoice_iban") +'\n'+_('BIC: ') + _invoice_details["invoice_bic"] +'\n' +_('Bank: ') + _invoice_details['invoice_bankname'] + _invoice_details['invoice_bankplace'] +'\n'+ _('Amount: ') + _amount_formated +' '+ _invoice_details['currency']+'\n'+_('Please use the following payment reference for your money transfer, as only through this way your payment is matched and assigned to the order:')+'\n'+'Payment Reference 1: ' + 'BNR-'+str(_payment_acquirer.novalnet_product.strip()) +'-'+ _order_no+'\n'+'Payment Reference 2: '+ ' TID '+_invoice_details['tid']
        return _comments

    """ Payment details based on the Invoice type
    >>> _invoice_type(_invoice_type)
    array
    """
    def _invoice_type(self, _invoice_type):
        return { 'payment_name': _('Invoice'), 'payment_method_type':'novalnet_invoice'} if _invoice_type.lower() == 'invoice' else { 'payment_name': _('Prepayment'), 'payment_method_type':'novalnet_prepayment'}

    """ Decodes the given string
    >>> self._novalnet_generate_decode(_data, _access_key)
    string
    """
    def _decode(self, _data, _access_key,uniqid):
        try:
            enc = base64.b64decode(_data)
            cipher = AES.new(_access_key, AES.MODE_CBC, uniqid )
            return _unpad(cipher.decrypt( enc ))
        except:
            return _data

    def _get_respons_amount(self,_amount):
        try:
           return int(_amount)
        except ValueError :
           return float(_amount)*100
