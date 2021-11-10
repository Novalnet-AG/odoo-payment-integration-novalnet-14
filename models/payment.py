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
            reference_tid bigint NOT NULL,
            callback_tid bigint DEFAULT NULL,
            callback_log text,
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
    novalnet_order_completion_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order completion status'), default='done')
    novalnet_invoice_callback_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Callback order status'),default='done')
    novalnet_prepayment_callback_order_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Callback order status'),default='done')
    paypal_payment_pending_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order status for the pending payment'), default='done')
    przelewy24_payment_pending_status = fields.Selection([('draft', _('Draft')), ('pending', _('Pending')),
                                                 ('done', _('Done')), ('error', _('Error')),
                                                 ('cancel', _('Canceled'))
                                                 ],_('Order status for the pending payment'), default='done')
    novalnet_manual_check_limit = fields.Char(_('Set a limit for on-hold transaction (in minimum unit of currency. E.g. enter 100 which is equal to 1.00)'), help=_('In case the order amount exceeds mentioned limit, the transaction will be set on hold till your confirmation of transaction'))
    novalnet_enable_cc3d = fields.Boolean(_('Enable 3D secure'), default=False, help=_('The 3D-Secure will be activated for credit cards. The issuing bank prompts the buyer for a password what, in turn, help to prevent a fraudulent payment. It can be used by the issuing bank as evidence that the buyer is indeed their card holder. This is intended to help decrease a risk of charge-back.'))
    novalnet_sepa_due_date = fields.Char(_('SEPA payment duration (in days)'), help=_('Enter the number of days after which the payment should be processed (must be greater than 6 days)'))
    novalnet_invoice_due_date = fields.Char(_('Payment due date (in days)'), help=_('Enter the number of days to transfer the payment amount to Novalnet (must be greater than 7 days). In case if the field is empty, 14 days will be set as due date by default'))
    novalnet_invoice_payment_reference_1 = fields.Boolean(_('Payment Reference 1 (Novalnet Invoice Reference)'), default=True)
    novalnet_invoice_payment_reference_2 = fields.Boolean(_('Payment Reference 2 (TID)'), default=True)
    novalnet_invoice_payment_reference_3 = fields.Boolean(_('Payment Reference 3 (Order No)'), default=True)
    novalnet_prepayment_payment_reference_1 = fields.Boolean(_('Payment Reference 1 (Novalnet Invoice Reference)'), default=True)
    novalnet_prepayment_payment_reference_2 = fields.Boolean(_('Payment Reference 2 (TID)'), default=True)
    novalnet_prepayment_payment_reference_3 = fields.Boolean(_('Payment Reference 3 (Order No)'), default=True)
    novalnet_referrer_id = fields.Char(_('Referrer ID'), help=_('Enter the referrer ID of the person/company who recommended you Novalnet'))
    novalnet_transaction_reference_1 = fields.Char(_('Transaction reference 1'), help=_('This reference will appear in your bank account statement'))
    novalnet_transaction_reference_2 = fields.Char(_('Transaction reference 2'), help=_('This reference will appear in your bank account statement'))
    novalnet_callbackscript_test_mode = fields.Boolean(_('Deactivate IP address control (for test purpose only)'),default=False,help=_('This option will allow performing a manual execution. Please disable this option before setting your shop to LIVE mode, to avoid unauthorized calls from external parties (excl. Novalnet).'))
    novalnet_callbackscript_email = fields.Boolean(_('Enable E-mail notification for callback'),default=False)
    novalnet_callbackscript_email_from = fields.Char(_('E-mail address (From)'), help=_('E-mail address of the sender'))
    novalnet_callbackscript_email_to = fields.Char(_('E-mail address (To)'), help=_('E-mail address of the recipient'))
    novalnet_callbackscript_email_bcc = fields.Char(_('E-mail address (Bcc)'), help=_('E-mail address of the recipient for BCC'))
    novalnet_callbackscript_notify_url = fields.Char(_('Notification URL'), help=_('The notification URL is used to keep your database/system actual and synchronizes with the Novalnet transaction status.'))

    """ Returns encoded values
    """
    def _encode_data(self, encode_values, access_key):
        for key, value in encode_values.items():
            encode_values[key] = self._generate_encode(encode_values[key], access_key)
        return encode_values

    """ Encodes the given string
    >>> self._generate_encode(_value, _access_key)
    string
    """
    def _generate_encode(self, _value, _access_key ):
        try:
            values = str(_value)
            crc_values = values.encode('latin-1')
            crc = '%u' % (binascii.crc32(crc_values) & 0xffffffff)
            data = crc + "|" + values
            data = data+_access_key
            data = data.encode('latin-1')
            data = binascii.hexlify(data)
            encoded = base64.b64encode(data)
            return encoded[::-1]
        except:
            return False

    """ Generating hash for the encoded values
    >>> self._generate_hashing(_values, _access_key)
    string
    """
    def _generate_hash(self, _values, _access_key):
        auth_code = _values['auth_code'].decode("utf-8")
        product = _values['product'].decode("utf-8")
        tariff = _values['tariff'].decode("utf-8")
        amount = _values['amount'].decode("utf-8")
        test_mode = _values['test_mode'].decode("utf-8")
        uniqid = _values['uniqid'].decode("utf-8")
        data = ''.join([
            auth_code,
            product,
            tariff,
            amount,
            test_mode,
            uniqid,
            _access_key[::-1]])
        return hashlib.md5(data.encode('utf-8')).hexdigest()

    """ Core function to form hidden values
    >>> %s_form_generate_values(_values)
    array
    """
    @api.multi
    def novalnet_form_generate_values(self, _values):
        _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        _remote_address = self.get_client_ip()
        _remote_address = self.is_valid_ipv6_address(_remote_address)
        _server_address = socket.gethostbyname(socket.gethostname())
        _server_address = self.is_valid_ipv6_address(_server_address)
        _order_amount = float(_values['amount']) *100

        """ Formating Order amount to cents """
        _order_formated_amount = '%g' % _order_amount

        """ Initiate the parameters """
        _transaction_values = {
            'gender' : 'u',
            'amount' : _order_formated_amount,
            'test_mode' : '1' if self.novalnet_test_mode or self.environment != 'prod' else '0',
            'system_name': 'odoo'+__version__,
            'system_version': __version__+'-NN2.0.1',
            'system_ip': '127.0.0.1' if _server_address is True or _server_address == '' else _server_address,
            'system_url': '%s' % urls.url_join(_base_url, ''),
            'lang': 'de' if _values['partner_lang'] == 'de_DE' else 'en',
            'language': 'de' if _values['partner_lang'] == 'de_DE' else 'en',
            'reference': _values['reference'],
            'remote_ip': '127.0.0.1' if _remote_address is True or _remote_address == '' else _remote_address,
            'return_url': '%s' % urls.url_join(_base_url, '/payment/novalnet/return/'),
            'error_return_url': '%s' % urls.url_join(_base_url, '/payment/novalnet/return/'),
            'return_method': 'POST',
            'error_return_method': 'POST',
            'currency': _values['currency'].name,
            'street': _values.get('billing_partner_address'),
            'search_in_street': '1',
            'city': _values.get('billing_partner_city'),
            'country_code': _values.get('billing_partner_country').code,
            'email': _values.get('billing_partner_email'),
            'zip_code': _values.get('billing_partner_zip'),
            'implementation': 'PHP',
            'first_name': _values.get('billing_partner_first_name') if _values.get('billing_partner_first_name') != '' else _values.get('billing_partner_last_name'),
            'last_name': _values.get('billing_partner_last_name') if _values.get('billing_partner_last_name') != '' else values.get('billing_partner_first_name'),
            'tel': _values.get('billing_partner_phone'),
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
        _get_manual_check_limit = self._is_valid_digit(self.novalnet_manual_check_limit)
        if _get_manual_check_limit and self._is_valid_digit(_transaction_values['amount']) >= _get_manual_check_limit:
            _transaction_values['on_hold'] = 1

        """ Check for Credit card 3d """
        if self.novalnet_enable_cc3d:
            _transaction_values['novalnet_cc_3d'] = 1

        """ Check for transaction references """
        if self.novalnet_transaction_reference_1 != False:
            _transaction_reference1 = re.compile(r'<[^<]*?/?>').sub('', self.novalnet_transaction_reference_1).strip()
            if _transaction_reference1 != '':
                _transaction_values['input1'] = 'Reference1'
                _transaction_values['inputval1'] = _transaction_reference1
        if self.novalnet_transaction_reference_2 != False:
            _transaction_reference2 = re.compile(r'<[^<]*?/?>').sub('', self.novalnet_transaction_reference_2).strip()
            if _transaction_reference2 != False:
                _transaction_values['input2'] = 'Reference2'
                _transaction_values['inputval2'] = _transaction_reference2
        return self._parameters_validation(_transaction_values)


    """" check remote and server ip are ipv6 
    """
    def is_valid_ipv6_address(self,address):
        try:
            socket.inet_pton(socket.AF_INET6, address)
        except socket.error:  # not a valid address
            return address
        return True


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
        _sepa_due_date    = self._is_valid_digit(self._strip_remove_space(self.novalnet_sepa_due_date))
        _transaction_values['vendor']    = _vendor
        """ Basic parameters validation """
        if not _access_key or not _auth_code or not self._is_valid_digit(_product) or not self._is_valid_digit(_tariff) or not self._is_valid_digit(_vendor):
            _transaction_values ['novalnet_validation_message'] = _('Basic parameter not valid')
            return _transaction_values

        """ Payment reference validation """
        if not self.novalnet_invoice_payment_reference_1 and not self.novalnet_invoice_payment_reference_2 and not self.novalnet_invoice_payment_reference_3:
            _transaction_values ['novalnet_validation_message'] = _('Please select atleast one payment reference.')
            return _transaction_values
            
        if not self.novalnet_prepayment_payment_reference_1 and not self.novalnet_prepayment_payment_reference_1 and not self.novalnet_prepayment_payment_reference_3:
            _transaction_values ['novalnet_validation_message'] = _('Please select atleast one payment reference.')
            return _transaction_values

        """ Due date validations """
        if _sepa_due_date and _sepa_due_date <= 6:
            _transaction_values ['novalnet_validation_message'] = _('SEPA Due date is not valid')
            return _transaction_values
        _transaction_values['sepa_due_date'] = _sepa_due_date if _sepa_due_date and _sepa_due_date > 6 else '7'
        _transaction_values['invoice_due_date'] = _invoice_due_date if _invoice_due_date and _invoice_due_date >= 7 else '14'
        
        """Forming encoded values """
        encode_values = {"product": _product,"auth_code": _auth_code, 'tariff':_tariff,'amount':_transaction_values['amount'],'test_mode':_transaction_values['test_mode'],'uniqid':int( random.random()*10000000000000000) }
        encode_details= self._encode_data(encode_values, _access_key)
        _transaction_values = _transaction_values.copy()
        _transaction_values.update(encode_details)
        _transaction_values['hash'] = self._generate_hash(encode_details, _access_key)
        return _transaction_values

    def _strip_remove_space(self, _data):
        return _data.strip() if _data else False

    """ Core function to append form
    action URL
    >>> %s_get_form_action_url()
    string
    """
    @api.multi
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

        """ Convert status inti integer to use further """
        _status_code = int(data.get('status', '0'))
        _tid_status_code = int(data.get('tid_status', '0'))

        _payment_key = data.get('payment_id') if data.get('key') != '6' and data.get('key') == None else data.get('key')
        _payment_property = self._get_payment_method(_payment_key)

        """ Get Novalnet configuration details """
        _payment_acquirer = self.acquirer_id

        _test_mode = self._decode(data.get('test_mode'),_payment_acquirer.novalnet_access_key)

        """ Check for test mode """
        _test_mode = '1' if _payment_acquirer.novalnet_test_mode or _payment_acquirer.environment != 'prod' or _test_mode != '0' else '0'

        """ Forming basic comments """
        _comments = self._form_basic_comments(_payment_property['payment_name'], data.get('tid'), _test_mode)

        """ Get Novalnet response message """
        _response_message = self._get_status_message(data)
        _logger.info(_response_message)

        _orginal_order_no = self.reference.split('-')

        _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        _url = '%s' % urls.url_join(_base_url, '')

        _order_amount =  self._decode(data.get('amount'),_payment_acquirer.novalnet_access_key)        
        _amount = self._get_respons_amount(_order_amount)
        _server_amount = '%g' % _amount

        if _status_code == 100 or (_status_code == 90 and data.get('key') == '34'):

            """ Unset the cart session """
            request.session['sale_order_id'] = None

            """ Get compelete order status """
            _order_status = _payment_acquirer.novalnet_order_completion_status
            """ Get values to be insert in Novalnet table """
            _order_amount =  self._decode(data.get('amount'),_payment_acquirer.novalnet_access_key)
            _amount = self._get_respons_amount(_order_amount)
            _server_amount = '%g' % _amount
            _callback_amount = _server_amount
            _base_url = self.env['ir.config_parameter'].get_param('web.base.url')
            _url = '%s' % urls.url_join(_base_url, '')

            if ((_status_code == '86' or _tid_status_code == '86') and data.get('key') == '78'):
                _callback_amount = 0
                _order_status = _payment_acquirer.przelewy24_payment_pending_status
            """ Paypal paending process """
            if _tid_status_code in [85,90] and data.get('key') == '34':
                _callback_amount = 0
                _order_status = _payment_acquirer.paypal_payment_pending_status

            """ Check for invoice payment """
            if data.get('payment_id') == '27':
                """ Assign callback_amount as zero for payment pending payments """
                _callback_amount = 0

                """ Assign order completion status """
                _order_status = _payment_acquirer.novalnet_order_completion_status 

                """ Check for invoice type """
                _payment_property = self._invoice_type(data.get('invoice_type'))

                """ Bank details array """
                _bank_details = {
                    'tid'               : data.get('tid'),
                    'due_date'          : data.get('due_date'),
                    'invoice_iban'      : data.get('invoice_iban'),
                    'invoice_bic'       : data.get('invoice_bic'),
                    'invoice_bankname'  : data.get('invoice_bankname').encode('latin1').decode('utf8'),
                    'invoice_bankplace' : data.get('invoice_bankplace').encode('latin1').decode('utf8'),
                    'amount'            : data.get('amount'),
                    'currency'          : data.get('currency')
                }

                """ Built comments with bank details """
                _comments = self._form_bank_comments(_payment_property['payment_name'], _bank_details, _payment_acquirer, self.reference, _test_mode,_payment_property['payment_method_type'])

            """ Maintaining log for callback process """
            self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type) VALUES (%s, %s, %s, %s, %s, %s, %s)', (self.reference, _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type']))

            """ Update transaction comments in sale order note """
            self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
            self.env.cr.commit()

            """ Order updation """
            return self.write({
                'state': _order_status,
                'acquirer_reference': data.get('tid'),
                'state_message': _comments,
            })

        else:
            _callback_amount = 0
            """ Maintaining log for callback process """
            self.env.cr.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type) VALUES (%s, %s, %s, %s, %s, %s, %s)', (self.reference, _callback_amount, _server_amount, data.get("tid"), data.get("tid"), _url, _payment_property['payment_method_type']))

            """ Update transaction comments in sale order note """
            self.env.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments+_response_message+'\n', _orginal_order_no[0]))
            self.env.cr.commit()

            """ Cancel the order on server validation """
            return self.write({
                'state': 'cancel',
                'state_message': _comments +_response_message+'\n',
            })

    """ To get payment property based on
    the payment key
    >>> _get_payment_method(_key)
    array
    """
    def _get_payment_method(self, _key):
        _payment_array = {
            '6'  : { 'payment_name': _('Novalnet Credit Card'), 'payment_method_type': 'novalnet_cc' },
            '27' : { 'payment_name': _('Invoice / Prepayment'), 'payment_method_type': 'novalnet_invoice_prepayment' },
            '33' : { 'payment_name': _('Novalnet Instant Bank Transfer'), 'payment_method_type': 'novalnet_instant_bank_transfer' },
            '34' : { 'payment_name': _('Novalnet PayPal'), 'payment_method_type': 'novalnet_paypal' },
            '37' : { 'payment_name': _('Novalnet Direct Debit SEPA'), 'payment_method_type': 'novalnet_sepa' },
            '40' : { 'payment_name': _('Direct Debit SEPA'), 'payment_method_type': 'novalnet_sepa' },
            '41' : { 'payment_name': _('Invoice'), 'payment_method_type': 'novalnet_invoice' },
            '49' : { 'payment_name': _('Novalnet iDEAL'), 'payment_method_type': 'novalnet_ideal' },
            '50' : { 'payment_name': _('Novalnet eps'), 'payment_method_type': 'novalnet_eps' },
            '69' : { 'payment_name': _('Novalnet giropay'), 'payment_method_type': 'novalnet_giropay' },
            '78' : { 'payment_name': _('Novalnet Przelewy24'), 'payment_method_type': 'novalnet_przelewy24' },
            
            
        }

        """ Check wheather key is present in the reposne or not """
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
    def _form_basic_comments(self, _payment_name, _tid, _test_mode):
        return '\n'+_payment_name + _('\nNovalnet transaction ID: %s \n')% _tid + _('Test order\n') if _test_mode == '1' else '\n'+_payment_name + _('\nNovalnet transaction ID: %s \n')% _tid

    """ Generate Bank comments
    >>> _form_bank_comments(_payment_name, _bank_details, _payment_acquirer, _order_no)
    string
    """
    def _form_bank_comments(self, _payment_name, _bank_details, _payment_acquirer, _order_no, _test_mode,_payment_method = ''):
        _comments = self._form_basic_comments(_payment_name, _bank_details['tid'], _test_mode)
        _due_date = datetime.strptime(_bank_details['due_date'], '%Y-%m-%d').strftime('%d.%m.%Y')
        _comments = _comments + _('Please transfer the amount to the below mentioned account details of our payment processor Novalnet')+'\n'+_('Due date: ')+ _due_date+'\n'+_('Account holder: NOVALNET AG')+'\n' +_('IBAN: ')+ _bank_details.get("invoice_iban") +'\n'+_('BIC: ') + _bank_details["invoice_bic"] +'\n' +_('Bank: ') + _bank_details['invoice_bankname'] + _bank_details['invoice_bankplace'] +'\n'+ _('Amount: ') + _bank_details['amount'] +' '+ _bank_details['currency']

        if _payment_method != '':
            if _payment_method == 'novalnet_invoice':
                _array_counter = [_payment_acquirer.novalnet_invoice_payment_reference_1, _payment_acquirer.novalnet_invoice_payment_reference_2, _payment_acquirer.novalnet_invoice_payment_reference_3]
            elif _payment_method == 'novalnet_prepayment':
                _array_counter = [_payment_acquirer.novalnet_prepayment_payment_reference_1, _payment_acquirer.novalnet_prepayment_payment_reference_2, _payment_acquirer.novalnet_prepayment_payment_reference_3]

            """ Get payment reference value from Novanet configuration """
            _array_count_value = Counter(_array_counter)

            """ Form payment reference values """
            _array_comments_value = [ 'BNR-'+str(_payment_acquirer.novalnet_product.strip()) +'-'+ _order_no, 'TID ' + _bank_details['tid'], _('Order number ') + _order_no]
            _incremant_id = 0
            _comments = _comments +'\n'+_('Please use any one of the following references as the payment reference, as only through this way your payment is matched and assigned to the order: ') if _array_count_value[True] > 1 else _comments + _('\nPlease use the following payment reference for your money transfer, as only through this way your payment is matched and assigned to the order:')+'\n'
            """ Assigning payment reference values based on the Novalnet configurations """
            for (_key, _value) in enumerate(_array_counter):
                if _value == True:
                    _incremant_id += 1
                    _payment_reference = _('Payment Reference: ') if _array_count_value[True] == 1 else '\n'+_('Payment Reference %s: ') % (_incremant_id)
                    _comments = _comments + _payment_reference + _array_comments_value[_key]
        return _comments

    """ Payment details based on the Invoice type
    >>> _invoice_type(_invoice_type)
    array
    """
    def _invoice_type(self, _invoice_type):
        return { 'payment_name': _('Novalnet Invoice'), 'payment_method_type':'novalnet_invoice'} if _invoice_type.lower() == 'invoice' else { 'payment_name': _('Novalnet Prepayment'), 'payment_method_type':'novalnet_prepayment'}

    """ Decodes the given string
    >>> self._novalnet_generate_decode(_data, _access_key)
    string
    """
    def _decode(self, _data, _access_key):
        try:
            _server_data = base64.b64decode(str(_data[::-1]))
            _server_data = binascii.unhexlify(_server_data)
            _server_data = str(_server_data)
            _server_data = _server_data[0:(_server_data.find(_access_key))]
            _pos  = _server_data.find("|")
            if _pos == False:
                return("Error: CKSum not found!")
            _crc   = _server_data[0:_pos]
            _crc   = _crc.replace("'", "")
            _value = _server_data[_pos + 1:]
            crc_values = _value.encode('latin-1')
            _check_crc = '%u' % (binascii.crc32(crc_values) & 0xffffffff)     
            _crc   = _check_crc.replace("'", "")
            if (_crc != _check_crc):
                return ("Error; CKSum invalid!")

            return _value
        except:
            return _data

    def _get_respons_amount(self,_amount):
        try:
           return int(_amount)
        except ValueError :
           return float(_amount)*100
