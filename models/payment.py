# coding: utf-8

import base64
import binascii
import hashlib
import logging
import socket
import random
import re
import odoo
import json

from urllib.parse import urlparse, parse_qs, parse_qsl

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

import requests
import pprint
from requests.exceptions import HTTPError

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
    novalnet_vendor = fields.Char(_('Merchant ID'), help=_('Enter Novalnet merchant ID'))
    novalnet_auth_code = fields.Char(_('Authentication code'), help=_('Enter Novalnet authentication code'))
    novalnet_product = fields.Char(_('Project ID'), help=_('Enter Novalnet project ID'))
    novalnet_tariff = fields.Char(_('Tariff ID'), help=_('Enter Novalnet tariff ID'))
    novalnet_access_key = fields.Char(_('Payment access key'), help=_('Enter the Novalnet payment access key'))
    novalnet_completion_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_on_hold_confirmation_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Onhold order status'),default='pending')
    novalnet_pending_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order status for the pending payment'), default='pending')
    novalnet_callback_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Callback order status'),default='done')
    novalnet_on_hold_cancellation_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Cancellation order status'),default='cancel')
    novalnet_manual_check_limit = fields.Selection([('capture',_('Capture')),('authorize',_('Authorize'))],_('Payment action'), default='capture')
    novalnet_manual_check_limit_amount = fields.Char(_('Minimum transaction limit for authorization(in minimum unit of currency. E.g. enter 100 which is equal to 1.00)'), help=_('In case the order amount exceeds the mentioned limit, the transaction will be set on-hold till your confirmation of the transaction. You can leave the field empty if you wish to process all the transactions as on-hold.'))
    novalnet_enable_cc3d = fields.Boolean(_('Enable 3D secure'), default=False, help=_('The 3D-Secure will be activated for credit cards. The issuing bank prompts the buyer for a password what, in turn, help to prevent a fraudulent payment. It can be used by the issuing bank as evidence that the buyer is indeed their card holder. This is intended to help decrease a risk of charge-back.'))
    novalnet_sepa_due_date = fields.Char(_('SEPA payment duration (in days)'), help=_('Enter the number of days after which the payment should be processed (must be between 2 and 14 days)'))
    novalnet_invoice_due_date = fields.Char(_('Payment due date (in days)'), help=_('Enter the number of days to transfer the payment amount to Novalnet (must be greater than 7 days). In case if the field is empty, 14 days will be set as due date by default'))
    novalnet_cashpayment_slip_expiry_date = fields.Char(_('Slip expiry date (in days)'), help=_('Enter the number of days to pay the amount at store near you. If the field is empty, 14 days will be set as default.'))
    novalnet_referrer_id = fields.Char(_('Referrer ID'), help=_('Enter the referrer ID of the person/company who recommended you Novalnet'))
    novalnet_callbackscript_test_mode = fields.Boolean(_('Deactivate IP address control (for test purpose only)'),default=False,help=_('This option will allow performing a manual execution. Please disable this option before setting your shop to LIVE mode, to avoid unauthorized calls from external parties (excl. Novalnet).'))
    novalnet_callbackscript_email = fields.Boolean(_('Enable E-mail notification for callback'),default=False)
    novalnet_callbackscript_email_from = fields.Char(_('E-mail address (From)'), help=_('E-mail address of the sender'))
    novalnet_callbackscript_email_to = fields.Char(_('E-mail address (To)'), help=_('E-mail address of the recipient'))
    novalnet_callbackscript_email_bcc = fields.Char(_('E-mail address (Bcc)'), help=_('E-mail address of the recipient for BCC'))

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
        _remote_address = self._get_client_ip()
        _server_address = socket.gethostbyname(socket.gethostname())
        _order_amount = float(_values['amount']) *100

        """ Formatting Order amount to cents """
        _order_formated_amount = '%g' % _order_amount

        """ Initiate the parameters """
        _transaction_values = {
            'gender'             : 'u',
            'amount'             : _order_formated_amount,
            'test_mode'          : '1' if self.state == 'test' else '0',
            'system_name'        : 'odoo'+__version__,
            'system_version'     : __version__+'-NN2.2.0',
            'system_ip'          : _server_address,
            'system_url'         : '%s' % urls.url_join(_base_url, ''),
            'address_form'       : '0',
            'thide'              : '1',
            'shide'              : '1',
            'lhide'              : '1',
            'hfooter'            : '0',
            'skip_cfm'           : '1',
            'lang'               : 'de' if _values['partner_lang'] == 'de_DE' else 'en',
            'reference'          : _values['reference'],
            'remote_ip'          : _remote_address,
            'return_url'         : '%s' % urls.url_join(_base_url, NovalnetController._return_url),
            'error_return_url'   : '%s' % urls.url_join(_base_url, NovalnetController._return_url),
            'return_method'      : 'GET',
            'error_return_method': 'GET',
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
            'rrt'                : 1,
        }
        
        
        """ Add sale order ID in the return_url and error_return_url refill the order session on return """
        _return_url = '%s' % urls.url_join(_base_url, NovalnetController._return_url)
        if _return_url.find("?") == -1:
            _return_url = _return_url + '?sale_order_id='+  _values['reference']
        else:
            _return_url = _return_url + '&sale_order_id='+  _values['reference']
        _transaction_values['return_url']       = _return_url
        _transaction_values['error_return_url'] = _return_url

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
    >>> _get_client_ip()
    """
    def _get_client_ip(self):
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
        _access_key          = self._strip_remove_space(self.novalnet_access_key)
        _auth_code           = self._strip_remove_space(self.novalnet_auth_code)
        _product             = self._strip_remove_space(self.novalnet_product)
        _tariff              = self._strip_remove_space(self.novalnet_tariff)
        _vendor              = self._strip_remove_space(self.novalnet_vendor)
        _invoice_due_date    = self._is_valid_digit(self._strip_remove_space(self.novalnet_invoice_due_date))
        _cp_slip_expiry_date = self._is_valid_digit(self._strip_remove_space(self.novalnet_cashpayment_slip_expiry_date))
        _sepa_due_date       = self._is_valid_digit(self._strip_remove_space(self.novalnet_sepa_due_date))
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

        if _cp_slip_expiry_date:
            _transaction_values['cp_due_date'] = _cp_slip_expiry_date

        """Forming encoded values """
        encode_values = {"product": _product,"auth_code": _auth_code, 'tariff':_tariff,'amount':_transaction_values['amount'],'test_mode':_transaction_values['test_mode'] }
        unique_id = str(int(random.random()*10000000000000000))[-16:]
        unique_id = str(int(random.random()*10000000000000000))[-16:] if len(unique_id) != 16 else unique_id
        encode_details= self._encode_data(encode_values, _access_key,unique_id)
        _transaction_values = _transaction_values.copy()
        _transaction_values.update(encode_details)
        _transaction_values['uniqid'] = unique_id
        _transaction_values['hash'] = self._generate_hash(encode_details, _access_key,unique_id)
        return _transaction_values

    """ Remove spaces
    >>> _strip_remove_space(data)
    """
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
            
    """ Core function to support token process
    >>> _get_feature_support()
    array
    """
    def _get_feature_support(self):

        res = super(AcquirerNovalnet, self)._get_feature_support()
        res['tokenize'].append('novalnet')
        return res
    
    """ Core function to token process
    >>> %s_s2s_form_proces()
    array
    """
    @api.model
    def novalnet_s2s_form_process(self, data):
        payment_token = []
        token_name = data.get('token_name')
        if token_name:
            payment_token = self.env['payment.token'].sudo().create({
                'acquirer_id': int(data['acquirer_id']),
                'partner_id': int(data['partner_id']),
                'novalnet_payment_method': data['payment_type'],
                'name': token_name,
                'acquirer_ref': data.get('tid')
            })
            return payment_token

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
        return self.search([('reference', '=', _data.get('sale_order_id'))])
        
    """ Core function to get
    transaction details
    >>> form_feedback(data, acquirer_name)
    array
    """
    @api.model
    def form_feedback(self, data, acquirer_name):

        if data.get('tid') and data.get('status') in  ['100', '90']:

            data_request = {
                "transaction" : {
                    "tid" : data.get('tid'),
                },
                "custom" : {
                    "lang" : 'DE' if self.partner_id.lang == 'de_DE' else 'EN',
                }
            }

            json_data = json.dumps(data_request);
            _novalnet_configuration = self.acquirer_id.search([('provider', '=', 'novalnet')], limit=1)
            json_response = self._get_txn_details('https://payport.novalnet.de/v2/transaction/details', json_data, _novalnet_configuration.novalnet_access_key);
            
            if 'result' not in json_response:
                try:
                    resp.raise_for_status()
                except HTTPError:
                    _logger.error(resp.text)
                    error_msg = " " + (_("Novalnet: Error occured while fetching the transaction details - '%s'") % resp.text)
                    raise ValidationError(error_msg)
        
            data.update(json_response)
        return super(TxNovalnet, self).form_feedback(data, acquirer_name)
    """ Initiate 
    Transaction details
    >>> _get_txn_details(data, access_key)
    array
    """
    def _get_txn_details(self, url, data, access_key):
        base64_bytes = base64.b64encode(access_key.encode('ascii'))
        base64_message = base64_bytes.decode('ascii')
        headers = {
            'Content-Type': 'application/json',
            'charset': 'utf-8',
            'Accept': 'application/json',
            'X-NN-Access-Key': base64_message,
        }
        resp = requests.request('POST', url, data=data, headers=headers)
        return resp.json()
    """ Core function to handle
    s2s (payment reference) payment call
    >>> _handle_s2s_response(data)
    array
    """
    @api.model
    def _handle_s2s_response(self, data):
        if self.acquirer_reference != False:
            _logger.warning('Order status already processed with the tid : %s' % self.acquirer_reference)
            return True
        if 'tid' in data and data.get('tid') != '':
            
            """ Convert status int integer to use further """
            _status_code = int(data.get('status', '0'))
            _tid_status_code = int(data.get('tid_status', '0'))
            
            """ Get payment key """
            _payment_key = ''
            if('payment_id' in data and data.get('payment_id') != None):
                _payment_key = data.get('payment_id') 
            if('key' in data and data.get('key') != None):
                _payment_key = data.get('key') 
            
            """ Assign payment type """
            _payment_type = ''
            if _payment_key == '6':
                _payment_type = 'CREDITCARD'
            elif _payment_key == '37':
               _payment_type = 'DIRECT_DEBIT_SEPA'
            
            _payment_property = self._get_payment_method(_payment_type)   
            """ Get Novalnet configuration details """
            _payment_acquirer = self.acquirer_id

            _test_mode = data.get('test_mode')
            
            """ Check for test mode """
            _test_mode = '1' if self.state == 'test' or _test_mode == '1' else '0'
            
            """ Forming basic comments """
            _comments = self._form_basic_comments(_payment_property['payment_name'], data.get('tid'), _payment_type, _test_mode, _tid_status_code)

            """ Get Novalnet response message """
            _response_message = self._get_status_message(data)
            _logger.info(_response_message)
            
            _orginal_order_no = self.reference.split('-')

            _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
            _url = '%s' % urls.url_join(_base_url, '')

            _order_amount =  data.get('amount')
            _amount = self._get_response_amount(_order_amount)
            _server_amount = '%g' % _amount
            _additional_info = ''

            if _status_code in [100, 90]:
               
                _callback_amount = _server_amount
                _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
                _url = '%s' % urls.url_join(_base_url, '')
                
                """ Onhold process """
                if _tid_status_code in [98, 99]:
                   _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status

                """ Assign order completion status """
                if _tid_status_code == 100:
                   _order_status = _payment_acquirer.novalnet_completion_order_status
                
                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status, additional_info) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)', (data.get("order_no"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code ,_additional_info))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                self.env.cr.commit()
               
                """ Order updation """
                if __version__ >= '12.0':
                    if _order_status == 'done':
                        self._set_transaction_done()
                        self.execute_callback()
                    elif _order_status == 'pending':
                        self._set_transaction_pending()
                self.write({'date': fields.datetime.now(),'state': _order_status,'acquirer_reference': data.get('tid'),'state_message': _comments})
                return True
                
            else:
                _callback_amount = 0
                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (data.get("order_no"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments+_response_message+'\n', _orginal_order_no[0]))
                self.env.cr.commit()

                """ Cancel the order on server validation """
                self._set_transaction_cancel()
                return self.write({
                    'state': 'cancel',
                    'state_message': _comments +_response_message+'\n',
                })
        else:
            self._set_transaction_error(_response_message)
            return self.write({
                'state': 'draft'
            })
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
            
        """ Get Novalnet response message """
        _response_message = self._get_status_message(data)
        _logger.info(_response_message)
        if 'tid' in data and data.get('tid') != '':
            
            """ Convert status int integer to use further """
            _status_code = int(data.get('status', '0'))
            _tid_status_code = 0
            if('tid_status' in data and data.get('tid_status') != ''):
                _tid_status_code = int(data.get('tid_status', '0'))
            if('payment_type' in data and data.get('payment_type') != ''):
                _payment_property = self._get_payment_method(data['payment_type'])

            """ Get Novalnet configuration details """
            _payment_acquirer = self.acquirer_id

            if 'transaction' in data:
                _test_mode = data['transaction']['test_mode']
                _test_mode = '1' if self.state == 'test' or data['transaction']['test_mode'] == 1 else '0'
            else:
                _test_mode = '1' if self.state == 'test' else '0'

            """ Check for test mode """
            _test_mode = '1' if self.state == 'test' or _test_mode != '0' else '0'

            """ Forming basic comments """
            _comments = ''
            
            if data['payment_type'] == 'INVOICE_START':
                _payment_property['payment_name'] = ''
                if data['transaction']['payment_type'] == 'INVOICE':
                    _payment_property['payment_name'] = _('Invoice')
                elif data['transaction']['payment_type'] == 'PREPAYMENT':
                    _payment_property['payment_name'] = _('Prepayment')
            _comments = self._form_basic_comments(_payment_property['payment_name'], data.get('tid'), data['payment_type'],_test_mode, _tid_status_code)

            _orginal_order_no = self.reference.split('-')

            _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
            _url = '%s' % urls.url_join(_base_url, '')

            _server_amount = 0
            if 'transaction' in data:
                _server_amount =  data['transaction']['amount']
            _additional_info = ''

            if _status_code in  [100, 90]:
                _callback_amount = _server_amount
                _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
                _url = '%s' % urls.url_join(_base_url, '')

                """ Pending process """
                if _tid_status_code in [86, 90] and data['transaction']['payment_type'] in ['PRZELEWY24','PAYPAL']:
                    _callback_amount = 0
                    _order_status = _payment_acquirer.novalnet_pending_order_status
                """ Onhold process """
                if _tid_status_code in [85, 91, 98, 99]:
                   if data['payment_type'] in ['PAYPAL','INVOICE_START']:
                      _callback_amount = 0
                   _order_status = _payment_acquirer.novalnet_on_hold_confirmation_status

                """ Check for Cashpayment payment """
                if data['payment_type'] == 'CASHPAYMENT' and _tid_status_code == 100:
                    _callback_amount = 0
                    _comments = _comments + _('Slip Expire date: %s') % data['transaction']['due_date']
                    if 'nearest_stores' in data['transaction']:
                        self.env.cr.execute("SELECT to_regclass('schema_name.res_country')")
                        _get_country = self.env.cr.fetchone()
                        _store_comments = ''
                        for _incremant_id, address in data['transaction']['nearest_stores'].items():
                                if address['store_name'] != '':
                                    _store_title_comments = '\n' + address['store_name']
                                if address['street'] != '':
                                    _store_street_comments = address['street']
                                if address['city'] != '':
                                    _store_city_comments = address['city']
                                if address['zip'] != '':
                                    _store_zipcode_comments = address['zip']
                                if address['country_code'] != '':
                                    _store_country_comments = address['country_code']
                                _store_comments += _store_title_comments + '\n' + _store_street_comments + '\n' + _store_city_comments + '\n' + _store_zipcode_comments + '\n' +_store_country_comments + '\n'
                        _comments = _comments + '\n' +_store_comments
                """ Check for invoice payment """
                if data['payment_type'] == 'INVOICE_START' and _tid_status_code == 100:
                    """ Assign callback_amount as zero for payment pending payments """
                    _callback_amount = 0

                    """ Bank details array """
                    _invoice_details = {
                        'invoice_account_holder' : data['transaction']['bank_details']['account_holder'],
                        'tid'                    : data['transaction']['tid'],
                        'due_date'               : data['transaction']['due_date'],
                        'invoice_iban'           : data['transaction']['bank_details']['iban'],
                        'invoice_bic'            : data['transaction']['bank_details']['bic'],
                        'invoice_bankname'       : data['transaction']['bank_details']['bank_name'],
                        'invoice_bankplace'      : data['transaction']['bank_details']['bank_place'],
                        'amount'                 : data['transaction']['amount'],
                        'currency'               : data['transaction']['currency'],
                    }
                    """ Built comments with bank details """
                    if _tid_status_code in [100, 91]:
                        _comments = _comments + self._form_bank_comments(_invoice_details, _payment_acquirer, self.reference)
                if data['payment_type'] in ['CREDITCARD', 'DIRECT_DEBIT_SEPA', 'GUARANTEED_DIRECT_DEBIT_SEPA'] and _tid_status_code in [99, 98, 100] and self.type == 'form_save':
                    token_name = ''
                    if 'transaction' in data:
                        if data['payment_type'] in ['CREDITCARD']: 
                            _card_expiry_month = str(data['transaction']['payment_data']['card_expiry_month'])
                            if(len(_card_expiry_month) < 2):
                                _card_expiry_month = str(0) + str(data['transaction']['payment_data']['card_expiry_month'])
                            _cc_no = data['transaction']['payment_data']['card_number'][-4:]
                            _cc_card_type = data['transaction']['payment_data']['card_brand']
                            _cc_expiry    = _card_expiry_month +'/'+ str(data['transaction']['payment_data']['card_expiry_year'])
                            token_name    = _cc_card_type + ' ' + _('ending in %s (expires ') % (_cc_no) + str(_cc_expiry) +')'
                        elif data['payment_type'] in ['DIRECT_DEBIT_SEPA', 'GUARANTEED_DIRECT_DEBIT_SEPA']: 
                            token_name   = (_('IBAN (Direct Debit SEPA) %s') % (data['transaction']['payment_data']['iban']))
                        if token_name != '':
                            token_data = {
                                "partner_id"   : self.partner_id.id,
                                "acquirer_id"  : self.acquirer_id.id,
                                "token_name"   : token_name,
                                "tid"          : data['transaction']['tid'],
                                "payment_type" : data['transaction']['payment_type'],
                            }
                            token = self.acquirer_id.novalnet_s2s_form_process(token_data)
                            self.payment_token_id = token.id
                            if self.payment_token_id:
                               self.payment_token_id.verified = True

                """ Assign order completion status """
                if _tid_status_code == 100:
                   _order_status = _payment_acquirer.novalnet_completion_order_status

                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status, additional_info) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)', (data.get("sale_order_id"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code ,_additional_info))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                self.env.cr.commit()

                """ Order updation """
                if __version__ >= '12.0':
                    if _order_status == 'done':
                        self._set_transaction_done()
                        self.execute_callback()
                    elif _order_status == 'pending':
                        self._set_transaction_pending()
                return self.write({'date': fields.datetime.now(),'state': _order_status,'acquirer_reference': data.get('tid'),'state_message': _comments})
            else:
                _callback_amount = 0
                """ Maintaining log for callback process """
                self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (data.get("sale_order_id"), _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type'], _tid_status_code))

                """ Update transaction comments in sale order note """
                self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments+_response_message+'\n', _orginal_order_no[0]))
                self.env.cr.commit()

                """ Cancel the order on server validation """
                self._set_transaction_cancel()
                return self.write({
                    'state': 'cancel',
                    'state_message': _comments +_response_message+'\n',
                })
        else:
            self._set_transaction_error(_response_message)
            return self.write({
                'state': 'draft'
            })
        return True
        
    """ generate hash
    >>> _generate_hash(values, _access_key, uniqid)
    string
    """
    def _generate_hash(self, values, _access_key, uniqid):
        auth_code = values['auth_code']
        product = values['product']
        tariff = values['tariff']
        amount = values['amount']
        test_mode = values['test_mode']
        data = ''.join([ auth_code, product, tariff, amount, test_mode, str(uniqid), _access_key[::-1]])
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

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
            'CREDITCARD'  : { 'payment_name': _('Credit Card'), 'payment_method_type': 'novalnet_cc' },
            'INVOICE' : { 'payment_name': _('Invoice'), 'payment_method_type': 'novalnet_invoice' },
            'INVOICE_START' : { 'payment_name': _('Invoice'), 'payment_method_type': 'novalnet_invoice' },
            'PREPAYMENT' : { 'payment_name': _('Prepayment'), 'payment_method_type': 'novalnet_prepayment' },
            'ONLINE_TRANSFER' : { 'payment_name': _('Instant Bank Transfer'), 'payment_method_type': 'novalnet_instant_bank_transfer' },
            'PAYPAL' : { 'payment_name': _('PayPal'), 'payment_method_type': 'novalnet_paypal' },
            'DIRECT_DEBIT_SEPA' : { 'payment_name': _('Direct Debit SEPA'), 'payment_method_type': 'novalnet_sepa' },
            'GUARANTEED_DIRECT_DEBIT_SEPA' : { 'payment_name': _('Direct Debit SEPA'), 'payment_method_type': 'novalnet_sepa' },
            'GUARANTEED_INVOICE' : { 'payment_name': _('Invoice'), 'payment_method_type': 'novalnet_invoice' },
            'IDEAL' : { 'payment_name': _('iDEAL'), 'payment_method_type': 'novalnet_ideal' },
            'EPS' : { 'payment_name': _('eps'), 'payment_method_type': 'novalnet_eps' },
            'CASHPAYMENT' : { 'payment_name': _('Cashpayment'), 'payment_method_type': 'novalnet_cashpayment' },
            'GIROPAY' : { 'payment_name': _('giropay'), 'payment_method_type': 'novalnet_giropay' },
            'PRZELEWY24' : { 'payment_name': _('Przelewy24'), 'payment_method_type': 'novalnet_przelewy24' },
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
    >>> _form_basic_comments(_payment_name, _tid, _payment_type, _test_mode, _tid_status)
    string
    """
    def _form_basic_comments(self, _payment_name, _tid, _payment_type, _test_mode, _tid_status):
        _comments = ''
        if _payment_type in ['GUARANTEED_INVOICE','GUARANTEED_DIRECT_DEBIT_SEPA']:
            _comments = 'This is processed as a guarantee payment\n'
        _comments =  _comments + '\n'+_payment_name + _('\nNovalnet transaction ID: %s \n')% _tid + _('Test order\n') if _test_mode == '1' else '\n'+_payment_name + _('\nNovalnet transaction ID: %s \n')% _tid
        if _tid_status == 75:
            if _payment_type in ['GUARANTEED_DIRECT_DEBIT_SEPA', '40']:
                _comments = _comments + 'Your order is under verification and we will soon update you with the order status. Please note that this may take upto 24 hours.'
            if _payment_type in ['GUARANTEED_INVOICE', '41']:
                _comments = _comments + 'Your order is under verification and once confirmed, we will send you our bank details to where the order amount should be transferred. Please note that this may take upto 24 hours.'
        return _comments

    """ Generate Bank comments
    >>> _form_bank_comments(_invoice_details, _payment_acquirer, _order_no)
    string
    """
    def _form_bank_comments(self, _invoice_details, _payment_acquirer, _order_no,_callback = False):
        _amount = float( _invoice_details['amount'])/100.0
        _amount_formated = ('%.2f' % _amount)
        _due_date = datetime.strptime(_invoice_details['due_date'], '%Y-%m-%d').strftime('%d.%m.%Y')
        _comments = _('Please transfer the amount to the below mentioned account details of our payment processor Novalnet')+'\n'+_('Due date: ')+ _due_date+'\n'+_('Account holder: ')+_invoice_details['invoice_account_holder']  +'\n' +_('IBAN: ')+ _invoice_details.get("invoice_iban") +'\n'+_('BIC: ') + _invoice_details["invoice_bic"] +'\n' +_('Bank: ') + _invoice_details['invoice_bankname'] + _invoice_details['invoice_bankplace'] +'\n'+ _('Amount: ') + _amount_formated +' '+ _invoice_details['currency']+'\n'+_('Please use the following payment reference for your money transfer, as only through this way your payment is matched and assigned to the order:')+'\n'+_('Payment Reference 1: ') + 'BNR-'+str(_payment_acquirer.novalnet_product.strip()) +'-'+ _order_no +'\n'+ _('Payment Reference 2: ')+ ' TID '+ str(_invoice_details['tid'])
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
            
    """ Get the response amount
    >>> self._get_response_amount(_amount)
    string
    """
    def _get_response_amount(self,_amount):
        try:
           return int(_amount)
        except ValueError :
           return float(_amount)*100

    def novalnet_s2s_do_transaction(self, **kwargs):
        self.ensure_one()
        _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        _remote_address = self.acquirer_id._get_client_ip()
        _server_address = socket.gethostbyname(socket.gethostname())
        _order_amount = float(self.amount) *100

        """ Formatting Order amount to cents """
        _order_formated_amount = '%g' % _order_amount

        """ Initiate the parameters """

        _transaction_values = {
            'gender'             : 'u',
            'amount'             : _order_formated_amount,
            'test_mode'          : '1' if self.acquirer_id.state == 'test' else '0',
            'system_name'        : 'odoo'+__version__,
            'system_version'     : __version__+'-NN2.2.0',
            'system_ip'          : _server_address,
            'system_url'         : '%s' % urls.url_join(_base_url, ''),
            'lang'               : 'de' if self.partner_id.lang == 'de_DE' else 'en',
            'remote_ip'          : _remote_address,
            'currency'           : self.currency_id.name,
            'street'             : self.partner_id.street,
            'search_in_street'   : '1',
            'city'               : self.partner_id.city,
            'country_code'       : self.partner_id.country_id.code,
            'email'              : self.partner_id.email,
            'zip'                : self.partner_id.zip,
            'first_name'         : self.partner_id.display_name,
            'last_name'          : self.partner_id.display_name,
            'tel'                : self.partner_id.phone,
            'vendor'             : self.acquirer_id.novalnet_vendor,
            'auth_code'          : self.acquirer_id.novalnet_auth_code,
            'product'            : self.acquirer_id.novalnet_product,
            'tariff'             : self.acquirer_id.novalnet_tariff,
            'payment_ref'        : self.payment_token_id.acquirer_ref,
            'payment_type'       : self.payment_token_id.novalnet_payment_method,
            'order_no'           : self.reference,
        }

        """ Check for company """
        if self.partner_id.company_name != False:
            _transaction_values['company'] = self.partner_id.company_name

        """ Check for On-Hold """
        _get_manual_check_limit_amount = self.acquirer_id._is_valid_digit(self.acquirer_id.novalnet_manual_check_limit_amount)
        if (self.acquirer_id.novalnet_manual_check_limit == 'authorize'  and  not _get_manual_check_limit_amount)  or (self.acquirer_id.novalnet_manual_check_limit == 'authorize'  and _get_manual_check_limit_amount and self.acquirer_id._is_valid_digit(_transaction_values['amount']) >= _get_manual_check_limit_amount):
            _transaction_values['on_hold'] = 1

        _sepa_due_date    = self.acquirer_id._is_valid_digit(self.acquirer_id._strip_remove_space(self.acquirer_id.novalnet_sepa_due_date))

        """ Due date validations """
        if _transaction_values['payment_type'] == 'DIRECT_DEBIT_SEPA' and _sepa_due_date and _sepa_due_date >=2 and _sepa_due_date <=14:
            _transaction_values['sepa_due_date'] = _sepa_due_date

        res = requests.post('https://payport.novalnet.de/paygate.jsp', data=_transaction_values, headers={})

        parsed_res = parse_qs(res.content.decode("utf-8") )
        arr = {}
        for key in parsed_res:
            arr[key] = parsed_res[key][0]
        arr['no_tokenization'] = 1
        return self._handle_s2s_response(arr)


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    novalnet_payment_method = fields.Char(string='Novalnet Payment Method', help='This contains the payment type of the token')
    provider = fields.Selection(string='Provider', related='acquirer_id.provider', readonly=False)
    save_token = fields.Selection(string='Save Cards', related='acquirer_id.save_token', readonly=False)

    @api.model
    def novalnet_create(self, values):
        if values.get('tid'):
            partner_id = self.env['res.partner'].browse(values.get('partner_id'))
            payment_acquirer = self.env['payment.acquirer'].browse(values.get('acquirer_id'))

            # create customer to stipe
            customer_data = {
                'email': partner_id.email
            }
            return {
                'acquirer_ref': values['tid'],
            }
        return values
