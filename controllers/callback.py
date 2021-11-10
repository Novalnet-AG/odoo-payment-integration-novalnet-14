# -*- coding: utf-8 -*-

import urlparse, re, logging, datetime,smtplib

from odoo import http, tools, SUPERUSER_ID
from odoo.http import request
from email.mime.multipart import MIMEMultipart
from email.MIMEText import MIMEText
from smtplib import SMTPException

_logger = logging.getLogger(__name__)

class NovalnetCallback(http.Controller):
    """ Zero level payment types """
    _zero_level_payment_type = { 'CREDITCARD', 'INVOICE_START', 'DIRECT_DEBIT_SEPA', 'GUARANTEED_INVOICE', 'GUARANTEED_DIRECT_DEBIT_SEPA', 'PAYPAL', 'ONLINE_TRANSFER', 'IDEAL', 'GIROPAY','PRZELEWY24','EPS'}

    """ First level payment types """
    _first_level_payment_type = {'PRZELEWY24_REFUND', 'RETURN_DEBIT_SEPA', 'REVERSAL', 'CREDITCARD_BOOKBACK', 'CREDITCARD_CHARGEBACK', 'PAYPAL_BOOKBACK', 'REFUND_BY_BANK_TRANSFER_EU'}

    """ Second level payment types """
    _second_level_payment_type = { 'ONLINE_TRANSFER_CREDIT','INVOICE_CREDIT', 'CREDIT_ENTRY_CREDITCARD', 'CREDIT_ENTRY_SEPA', 'DEBT_COLLECTION_SEPA', 'DEBT_COLLECTION_CREDITCARD'}

    """ Novalnet payments catagory """
    _payment_groups = {
        'novalnet_cc' : {
            'CREDITCARD',
            'CREDITCARD_BOOKBACK',
            'CREDITCARD_CHARGEBACK',
            'CREDIT_ENTRY_CREDITCARD',
            'DEBT_COLLECTION_CREDITCARD',
            'SUBSCRIPTION_STOP',
        },
        'novalnet_sepa' : {
            'DIRECT_DEBIT_SEPA',
            'RETURN_DEBIT_SEPA',
            'CREDIT_ENTRY_SEPA',
            'DEBT_COLLECTION_SEPA',
            'GUARANTEED_DIRECT_DEBIT_SEPA',
            'REFUND_BY_BANK_TRANSFER_EU',
            'SUBSCRIPTION_STOP',
        },
        'novalnet_ideal' : {
            'IDEAL',
            'REFUND_BY_BANK_TRANSFER_EU',
            'REVERSAL',
            'ONLINE_TRANSFER_CREDIT'
        },
        'novalnet_instant_bank_transfer' : {
            'ONLINE_TRANSFER',
            'ONLINE_TRANSFER_CREDIT',
            'REFUND_BY_BANK_TRANSFER_EU',
            'REVERSAL'
        },
        'novalnet_giropay' : {
            'GIROPAY',
            'REFUND_BY_BANK_TRANSFER_EU',
            'ONLINE_TRANSFER_CREDIT'
        },
        'novalnet_paypal' : {
            'PAYPAL',
            'PAYPAL_BOOKBACK',
            'SUBSCRIPTION_STOP',
            'REFUND_BY_BANK_TRANSFER_EU'
        },
        'novalnet_prepayment' : {
            'INVOICE_START',
            'INVOICE_CREDIT',
            'SUBSCRIPTION_STOP',
        },
        'novalnet_invoice' : {
            'INVOICE_START',
            'GUARANTEED_INVOICE',
            'INVOICE_CREDIT',
            'SUBSCRIPTION_STOP',
        },
        'novalnet_eps' : {
            'EPS',
            'REFUND_BY_BANK_TRANSFER_EU',
            'ONLINE_TRANSFER_CREDIT'
        },
        'novalnet_przelewy24' : {
            'PRZELEWY24',
            'PRZELEWY24_REFUND'
        },
    }

    """ Mandatory Parameters """
    _required_params = {
        'vendor_id',
        'status',
        'payment_type',
        'tid',
        'tid_status'
    }

    """ Success code for the Novalnet payments """
    _success_code = {
        'PAYPAL' : {
            '100',
            '90',
            '85'
        },
        'INVOICE_START' : {
            '100',
            '91',
        },
        'CREDITCARD' : {
            '100',
            '98',
        },
        'DIRECT_DEBIT_SEPA' : {
            '100',
            '99',
        },
        'GIROPAY' : {
            '100',
        },
        'ONLINE_TRANSFER' : {
            '100',
        },
        'IDEAL' : {
            '100',
        },
        'EPS' : {
            '100'
        },
        'PRZELEWY24' : {
            '100',
            '86'
        }
    }

    """ Allowed ip's """
    _ip_allowed = {
        '195.143.189.210',
        '195.143.189.214',
    }

    """ Get server request """
    _get_request = {}

    """ Get Order reference """
    _get_order = {}

    """ Success status """
    _success_status = False

    """ Load Novalnet configuration """

    _novalnet_configuration = False

    """ Novalnet Callback testmode """

    _test_mode = False

    """ Novalnet Callback testmode """
    _debug_mode = False

    """ Callback process
    >>> novalnet_callback_process(_post_data)
    """
    @classmethod
    def novalnet_callback_process(self, _post_data):

        """ Assign instance """
        callback_instance = NovalnetCallback()
        """ Gloabl variables """

        del _post_data['db']

        """ Get payment acquirer details """
        _payment_acquirer = request.env['payment.acquirer']

        """ Check for limit due to duplicate payment """
        callback_instance._novalnet_configuration = _payment_acquirer.search([('provider', '=', 'novalnet')], limit=1)

        """ Check for callback script testmode """
        callback_instance._test_mode = callback_instance._novalnet_configuration.novalnet_callbackscript_test_mode

        """ Check for callback script debug mode """
        callback_instance._debug_mode = callback_instance._novalnet_configuration.novalnet_callbackscript_debug_mode

        """ Check for ip authentication """
        novalnet_response = callback_instance._check_authentication()
        if(novalnet_response):
            return novalnet_response

        """ Check for empty request """
        if not _post_data:
            return callback_instance._display_message('Novalnet callback received. No params passed over!')

        """ Check affilitae process """
        if 'vendor_activation' in _post_data and _post_data['vendor_activation'] == '1':
            return callback_instance._check_affiliate(_post_data)

        """ Get Novalnet server request """
        callback_instance._get_request = callback_instance._get_server_request(_post_data)

        if(type(callback_instance._get_request).__name__ == 'str'):
            return callback_instance._get_request

        """ Get order reference for the given tid / order_no """
        callback_instance._get_order = callback_instance._get_order_reference(request.cr)

        if(type(callback_instance._get_order).__name__ == 'str'):
            return callback_instance._get_order

        """ Get payment level """
        _get_payment_level = callback_instance._get_payment_type_level()

        """ Success status for the callback execution """
        callback_instance._success_status = callback_instance._get_request['status'] == '100' and callback_instance._get_request['tid_status'] == '100'

        if callback_instance._get_request['status'] != '100' and callback_instance._get_request['tid_status'] == '100':
            return callback_instance._display_message('Novalnet callback received.status ['+callback_instance._get_request['status']+']is not valid: Only 100 is allowed')

        if callback_instance._get_request['status'] == '100' and callback_instance._get_request['tid_status'] != '100':
            return callback_instance._display_message('Novalnet callback received.tid_status['+callback_instance._get_request['tid_status']+']is not valid: Only 100 is allowed')

        if callback_instance._get_request['order_no'] == '' and callback_instance._get_request['status'] != '100' and callback_instance._get_request['tid_status'] != '100':
            return callback_instance._display_message('Novalnet callback received.tid_status['+callback_instance._get_request['tid_status']+']is not valid: Only 100 is allowed')
       
        """ Check for payment level 0 process """
        if _get_payment_level == 0 and callback_instance._get_request['status'] == '100' and callback_instance._get_request['tid_status'] in callback_instance._success_code [callback_instance._get_request['payment_type']]:
            return callback_instance._zero_level_process(request.cr)

        """ Check for payment level 1 process """
        if _get_payment_level == 1 and callback_instance._success_status:
            return callback_instance._first_level_process(request.cr)

        """ Check for payment level 2 process """
        if _get_payment_level == 2 and callback_instance._success_status:
            return callback_instance._second_level_process(request.cr)

        if callback_instance._get_request['payment_type'] == 'SUBSCRIPTION_STOP':
            """ Handling SUBSCRIPTION_STOP PROCESS """

        """ Order already executed """
        return callback_instance._display_message('Novalnet callbackscript already executed')

    """ Validate and get the request
    values from server
    >>> _get_server_request(_server_request)
    array
    """
    def _get_server_request(self, _server_request):

        """ Assign required tid parameter """
        _extra_required_param = ''
        if _server_request['payment_type'] not in self._zero_level_payment_type:
            _extra_required_param = ['tid_payment']
            self._required_params.update(['tid_payment'])
        elif 'tid_payment' in self._required_params and _server_request['payment_type'] in self._zero_level_payment_type:
            _extra_required_param = self._required_params.remove('tid_payment')

        """ Validate general parameters """
        for (key, value) in enumerate(self._required_params):
            if value not in _server_request or _server_request[value] == '':
                return self._display_message( 'Required param ( '+value+' ) missing!' )
            elif value in [_extra_required_param, 'tid'] and len(_server_request[value]) != 17:
                return self._display_message('Novalnet callback received. Invalid TID ['+value+'] for Order.')
            elif value in [_extra_required_param, 'tid_payment'] and len(_server_request[value]) != 17:
                return self._display_message('Novalnet callback received. Invalid TID ['+value+'] for Order.')

        if _server_request['payment_type'] != 'SUBSCRIPTION_STOP' and (_server_request['amount'] == '' or self.valid(_server_request['amount']) or _server_request['amount'] < 0):
            return self._display_message('Novalnet callback received. The requested amount is not valid')

        for (key, value) in enumerate(['invoice_type','invoice_bankname', 'due_date', 'invoice_bankplace', 'invoice_iban', 'invoice_bic']):
            if value not in _server_request:
                _server_request[value] = ''
        
        """ Validate payment_type """
        if 'payment_type' not in _server_request or (_server_request['payment_type'] not in self._first_level_payment_type and _server_request['payment_type'] not in self._second_level_payment_type and _server_request['payment_type'] not in self._zero_level_payment_type):
            self._display_message('Novalnet callback received. Payment type ( '+_server_request['payment_type']+' ) is mismatched!')

        """ Assign processing tid in shop_tid """
        _server_request['shop_tid'] = _server_request['tid_payment'] if _server_request['payment_type'] in self._first_level_payment_type or _server_request['payment_type'] in  self._second_level_payment_type else _server_request['tid']

        """ return server_request """
        return _server_request
    
    """ Validate amount """
    def valid(self,userInput):
        if userInput.isdigit() == False:
            return True
        return False


    """ Get Order reference
    to process callback
    >>> _get_order_reference(_cr_data, context_data)
    array
    """
    def _get_order_reference(self, _cr_data):

        """ Get order details from the novalnet_callback table using TID """
        order_details = _cr_data.execute('SELECT order_no, total_amount, callback_amount, payment_method_type from novalnet_callback WHERE reference_tid=%s', (self._get_request['shop_tid'],))
        _fetch_order_details = _cr_data.dictfetchone()


        """ Check for communication failure """
        if not _fetch_order_details and self._get_request['payment_type'] in self._zero_level_payment_type:
            if 'order_no' in self._get_request and self._get_request['order_no'] == '':
                return self._display_message('Novalnet callback received. order number invalid')
            return self._update_initial_payment(_cr_data)

        if self._get_request['payment_type'] not in self._payment_groups[_fetch_order_details['payment_method_type']]:
            return self._display_message('Novalnet callback received. Payment type mismatched')

        """ Check for order number mismatch """
        if 'order_no' not in self._get_request and self._get_request['order_no'] != _fetch_order_details['order_no']:
            return self._display_message('Novalnet callback received. order number invalid')
        return _fetch_order_details

    """ Handling communication failure
    >>> _update_initial_payment(_cr_data)
    """
    def _update_initial_payment(self, _cr_data):

        """ Get payment key based on the payment_type """
        _payment_key = self._get_payment_key(self._get_request['payment_type'])

        """ Get payment details """
        _payment_property = request.env['payment.transaction'].sudo()._get_payment_method(_payment_key)

        """ Form basic comments """
        _comments = request.env['payment.transaction'].sudo()._form_basic_comments(_payment_property['payment_name'], self._get_request['tid'], self._get_request['test_mode'])

        _orginal_order_no = self._get_request['order_no'].split('-')

        base_url = request.env['ir.config_parameter'].get_param('web.base.url')
        _url = '%s' % urlparse.urljoin(base_url, '')

        """ Check for succes transaction """
        if self._get_request['tid_status'] in self._success_code[self._get_request['payment_type']]:

            """ Assign order status """
            _order_status = self._novalnet_configuration.novalnet_order_completion_status
            _callback_amount = self._get_request['amount']

            """ Process invoice payments """
            if _payment_key == '27':

                """ Process pending payment """
                _callback_amount = 0
                _order_status = self._novalnet_configuration.novalnet_order_completion_status
                _amount_in_cents = self._get_request['amount']
                _callback_paid_amount = float(self._get_request['amount'])/100.0
                self._get_request['amount'] = ('%.2f' % _callback_paid_amount)
                _comments =  request.env['payment.transaction'].sudo()._form_bank_comments(_payment_property['payment_name'], self._get_request, self._novalnet_configuration, self._get_request['order_no'], self._get_request['test_mode'])
                self._get_request['amount'] = _amount_in_cents

            elif self._get_request['tid_status'] in ['90','85'] and _payment_key == '34':
                """ Process pending payment """
                _callback_amount = 0
                _order_status = self._novalnet_configuration.paypal_payment_pending_status
                
            elif _payment_key == '78' and self._get_request['tid_status'] == '86':
                """ Process pending payment """
                _callback_amount = 0
                _order_status = self._novalnet_configuration.przelewy24_payment_pending_status

            """ Insert the values in novalnet callback """
            _cr_data.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type) VALUES (%s, %s, %s, %s, %s, %s, %s)', (self._get_request['order_no'], _callback_amount, self._get_request['amount'], self._get_request['tid'], self._get_request['tid'], _url, _payment_property['payment_method_type']))
            _cr_data.commit()

            """ Update transaction comments and status in sale order note """
            _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s), state=%s WHERE name=%s', (_comments, 'sale', _orginal_order_no[0]))
            _cr_data.commit()

            """ Update the comments in payment_transaction table """
            _cr_data.execute('UPDATE payment_transaction SET acquirer_reference =%s, state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(self._get_request['tid'], _order_status, _comments, self._get_request['order_no']))
            _cr_data.commit()

        else:
            """ Handle other than 100 status """
            _comments = _comments + '\n' + self._get_request['status_message']
            _callback_amount = 0                
            _cr_data.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type) VALUES (%s, %s, %s, %s, %s, %s, %s)', (self._get_request['order_no'], _callback_amount, self._get_request['amount'], self._get_request['tid'], self._get_request['tid'], _url, _payment_property['payment_method_type']))
            _cr_data.commit()

            """ Update transaction comments in sale order note """
            _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
            _cr_data.commit()
            """ Update the comments in payment_transaction table """
            _cr_data.execute('UPDATE payment_transaction SET acquirer_reference =%s, state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(self._get_request['tid'], 'cancel', _comments, self._get_request['order_no']))
            _cr_data.commit()

        """ Process email """
        self._send_novalnet_callback_email(_comments)
        return self._display_message('Novalnet Callback Script executed successfully, Transaction details are updated')

    """ Get payment level
    based on the payment type
    >>> _get_payment_type_level()
    """
    def _get_payment_type_level(self):
        if self._get_request['payment_type'] in self._zero_level_payment_type:
            return 0
        if self._get_request['payment_type'] in self._first_level_payment_type:
            return 1
        if self._get_request['payment_type'] in self._second_level_payment_type:
            return 2

    """ Zero level process
    based on the payment type
    >>> _zero_level_process(_cr_data)
    """
    def _zero_level_process(self,_cr_data):
        if 'subs_billing' in self._get_request and self._get_request['subs_billing'] == '1':
            """Step1: THE SUBSCRIPTION IS RENEWED, PAYMENT IS MADE, SO JUST CREATE A NEW ORDER HERE WITHOUT A PAYMENT PROCESS AND SET THE ORDER STATUS AS PAID
            Step2: THIS IS OPTIONAL: UPDATE THE BOOKING REFERENCE AT NOVALNET WITH YOUR ORDER_NO BY CALLING NOVALNET GATEWAY, IF U WANT THE USER TO USE ORDER_NO AS PAYMENT REFERENCE
            Step3: ADJUST THE NEW ORDER CONFIRMATION EMAIL TO INFORM THE USER THAT THIS ORDER IS MADE ON SUBSCRIPTION RENEWAL
            """
            if self._get_request['payment_type'] == 'INVOICE_START':
                """ Step4: ENTER THE NECESSARY REFERENCE & BANK ACCOUNT DETAILS IN THE NEW ORDER CONFIRMATION EMAIL """
        elif self._get_request['payment_type'] in ['PAYPAL','PRZELEWY24'] and self._success_status and self._get_order['callback_amount'] < self._get_order['total_amount']:
            _callback_paid_amount = float(self._get_request['amount'])/100.0
            _amount_formated = ('%.2f' % _callback_paid_amount)
            """ Forming callback comments """
            _comments= '\n\nNovalnet Callback Script executed successfully for the TID: %s with amount %s %s on %s.' % (self._get_request['tid'], _amount_formated, self._get_request['currency'], datetime.datetime.now())

            """ Update callback comments and order status """
            _cr_data.execute('UPDATE payment_transaction SET state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(self._novalnet_configuration.novalnet_order_completion_status, _comments, self._get_order['order_no']))

            """ Update callback amount """
            _cr_data.execute('UPDATE novalnet_callback SET callback_amount=%s WHERE order_no=%s',(self._is_valid_digit(self._get_order['callback_amount']) + self._is_valid_digit(self._get_request['amount']), self._get_order['order_no']))
            _cr_data.commit()

            _orginal_order_no = self._get_order['order_no'].split('-')

            if self._novalnet_configuration.novalnet_order_completion_status == 'done':

                """ Update transaction comments in sale order note """
                _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s), state=%s WHERE name=%s', (_comments, 'sale', _orginal_order_no[0]))
                _cr_data.commit()
            else:

                """ Update transaction comments and status in sale order note """
                _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                _cr_data.commit()

            """ Process email """
            self._send_novalnet_callback_email(_comments)
            return self._display_message(_comments)
        else:
            return self._display_message('Novalnet Callbackscript received. Payment type is not applicable for this process!')


    """ First level process
    based on the payment type
    >>> _first_level_process(_cr_data)
    """
    def _first_level_process(self, _cr_data):

        """ DO THE STEPS TO UPDATE THE STATUS OF THE ORDER OR THE USER AND NOTE THAT THE PAYMENT WAS RECLAIMED FROM USER """
        """ Forming callback comments """
        _callback_paid_amount = float(self._get_request['amount'])/100.0
        _amount_formated = ('%.2f' % _callback_paid_amount)
        _comments = ('\n\nNovalnet callback received. Refund/Bookback executed successfully for the TID: %s amount: %s %s on %s. The subsequent TID: %s.' % (self._get_request['tid_payment'], _amount_formated, self._get_request['currency'], datetime.datetime.now(), self._get_request['tid'])) if self._get_request['payment_type'] in ['PAYPAL_BOOKBACK', 'CREDITCARD_BOOKBACK','PRZELEWY24_REFUND', 'REFUND_BY_BANK_TRANSFER_EU'] else ('\n\nNovalnet callback received. Chargeback executed successfully for the TID: %s amount: %s %s on %s. The subsequent TID: %s.' % (self._get_request['tid_payment'], _amount_formated, self._get_request['currency'], datetime.datetime.now(), self._get_request['tid']))

        """ Update callback comments and order status """
        _cr_data.execute('UPDATE payment_transaction SET state_message=CONCAT(state_message, %s) WHERE reference=%s',(_comments, self._get_order['order_no']))
        _cr_data.commit()

        _orginal_order_no = self._get_order['order_no'].split('-')

        """ Update transaction comments in sale order note """
        _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
        _cr_data.commit()

        """ Process email """
        self._send_novalnet_callback_email(_comments)
        return self._display_message(_comments)

    """ Second level process
    based on the payment type
    >>> _second_level_process(_cr_data)
    """
    def _second_level_process(self, _cr_data):

        """ Check for callback amount """

        if self._is_valid_digit(self._get_order['callback_amount']) < self._is_valid_digit(self._get_order['total_amount']):
            _callback_paid_amount = float(self._get_request['amount'])/100.0
            _amount_formated = ('%.2f' % _callback_paid_amount)
            """ Forming callback comments """
            _comments = '\n\nNovalnet Callback Script executed successfully for the TID: %s with amount %s %s on %s. Please refer PAID transaction in our Novalnet Merchant Administration with the TID: %s' % (self._get_request['tid_payment'], _amount_formated, self._get_request['currency'], datetime.datetime.now(), self._get_request['tid'])

            """ Calculate paid amount """
            _paid_amount = self._is_valid_digit(self._get_order['callback_amount']) + self._is_valid_digit(self._get_request['amount'])

            _orginal_order_no = self._get_order['order_no'].split('-')

            """ Update callback amount """
            _cr_data.execute('UPDATE novalnet_callback SET callback_amount=%s, callback_tid=%s WHERE order_no=%s',(_paid_amount, self._get_request['tid'], self._get_order['order_no']))
            _cr_data.commit()

            """ Calculate fully paid amount """
            if _paid_amount >= self._is_valid_digit(self._get_order['total_amount']) and self._get_request['payment_type'] in ['INVOICE_CREDIT','ONLINE_TRANSFER_CREDIT']:

                _payment_name = self._get_order['payment_method_type']
                
                if _payment_name == 'novalnet_invoice':
                    _callback_status = self._novalnet_configuration.novalnet_invoice_callback_order_status
                elif _payment_name == 'novalnet_prepayment':
                    _callback_status = self._novalnet_configuration.novalnet_prepayment_callback_order_status                
                elif self._get_request['payment_type'] == 'ONLINE_TRANSFER_CREDIT':
                    _callback_status = self._novalnet_configuration.novalnet_order_completion_status
                
                self._send_novalnet_callback_email(_comments)
                if _payment_name in ['novalnet_invoice','novalnet_prepayment'] :
                    _invoice_type = 'invoice' if _payment_name == 'novalnet_invoice' else 'prepayment'
                    _payment_property = request.env['payment.transaction'].sudo()._invoice_type(_invoice_type)
                else:
                    _get_payment_key = self._get_payment_keys(_payment_name)
                    _payment_property = request.env['payment.transaction'].sudo()._get_payment_method(_get_payment_key)             
                    
                _comments = request.env['payment.transaction'].sudo()._form_basic_comments(_payment_property['payment_name'], self._get_request['shop_tid'], self._get_request['test_mode'])
                """ Calculate paid amount greater than order amount """
                _mail_comment = _comments + 'Customer paid amount is greater than order amount.' if _paid_amount > self._is_valid_digit(self._get_order['total_amount']) else _comments

                """ Update Transaction comments without bank details """
                _cr_data.execute('UPDATE payment_transaction SET state=%s, state_message=%s WHERE reference=%s',(_callback_status, _comments, self._get_order['order_no']))
                _cr_data.commit()

                if _callback_status == 'done':

                    """ Update transaction comments in sale order note """
                    _cr_data.execute('UPDATE sale_order SET note=%s, state=%s WHERE name=%s', (_comments, 'sale', _orginal_order_no[0]))
                    _cr_data.commit()
                else:

                    """ Update transaction comments and status in sale order note """
                    _cr_data.execute('UPDATE sale_order SET note=%s WHERE name=%s', (_comments, _orginal_order_no[0]))
                    _cr_data.commit()

                """ Process email """
                self._send_novalnet_callback_email(_comments)
                return self._display_message(_mail_comment)

            """ Update Callback comments """
            _cr_data.execute('UPDATE payment_transaction SET state_message=CONCAT(state_message, %s) WHERE reference=%s',(_comments, self._get_order['order_no']))
            _cr_data.commit()

            """ Update transaction comments in sale order note """
            _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
            _cr_data.commit()

            """ Process email """
            self._send_novalnet_callback_email(_comments)
            return self._display_message(_comments)
        else:
            return self._display_message('Novalnet callbackscript already executed')



    """ Get payment key value
    >>> _get_payment_key(_payment_type)
    string
    """
    def _get_payment_key(self, _payment_type):
        _payment_key_array = {
            'novalnet_cc' : '6',
            'novalnet_invoice' : '27',
            'novalnet_prepayment' : '27',
            'novalnet_sepa' : '37',
            'novalnet_ideal' : '49',
            'novalnet_instant_bank_transfer' : '33',
            'novalnet_eps' : '50',
            'novalnet_giropay' : '69',
            'novalnet_paypal' : '34',
            'novalnet_przelewy24' : '78',
        }
        for (key, value) in self._payment_groups.iteritems():
             for (keys, values) in enumerate(value):
                if self._get_request['payment_type'] in value:
                    return _payment_key_array[key]        

    """ Check for authentication
    >>> _check_authentication()
    """
    def _check_authentication(self):
        remote_address = request.httprequest.headers.environ.get("REMOTE_ADDR")
        if remote_address not in self._ip_allowed and not self._test_mode:
            return self._display_message('Novalnet callback received. Unauthorised access from the IP ' + remote_address)
        return False

    """ Check for affiliate process
    >>> _check_affiliate(_post_data)
    """
    def _check_affiliate(self, _post_data):
        if 'vendor_activation' in _post_data and _post_data['vendor_activation'] == '1':
            _comments = """ Customize the affiliate process
            """
            return self._display_message(_comments)

    """ Process callback email
    >>> _send_novalnet_callback_email(_message)
    """
    def _send_novalnet_callback_email(self, _message):

        """ Check for callback email """
        if self._novalnet_configuration.novalnet_callbackscript_email and self._novalnet_configuration.novalnet_callbackscript_email_from != '' and self._novalnet_configuration.novalnet_callbackscript_email_to != '' :
            _email_from = self._novalnet_configuration.novalnet_callbackscript_email_from
            _email_to   = tools.email_split_and_format(self._novalnet_configuration.novalnet_callbackscript_email_to)
            _email_to   = ''.join(_email_to) 
            _email_bcc  = tools.email_split_and_format(self._novalnet_configuration.novalnet_callbackscript_email_bcc)
            _subject    = 'Novalnet odoo callback script'
            _body = _message
            """ Send email """
            _shop_mail_send = tools.email_send(_email_from, _email_to, _subject, _body, None, _email_bcc)
            
            if _shop_mail_send == False:
                msg = MIMEMultipart()
                msg['From'] = _email_from
                msg['To'] = ''.join(_email_to) 
                msg['Bcc'] = ''.join(_email_bcc) 
                msg['Subject'] = _subject
                msg.attach(MIMEText(_body))
                rcpt = ''.join(_email_bcc) .split(",") + [_email_to]
                try:
                    smtpObj = smtplib.SMTP('localhost')
                    smtpObj.sendmail(_email_from, rcpt, msg.as_string())
                except SMTPException:
                    return False

    """ Show callback process messages
    >>> _display_message(_message)
    """
    def _display_message(self, _message):
        if self._debug_mode or not self._test_mode :
            _logger.info(_message)
            return _message
        return "";


    """ Check for integer
    >>> _is_valid_digit(value)
    """
    def _is_valid_digit(self, _value):
        try:
            return int(_value)
        except ValueError:
            return False

    def _get_payment_keys(self,_payment_name):
        _payment_key_array = {
            'novalnet_cc' : '6',
            'novalnet_invoice' : '27',
            'novalnet_prepayment' : '27',
            'novalnet_sepa' : '37',
            'novalnet_ideal' : '49',
            'novalnet_instant_bank_transfer' : '33',
            'novalnet_eps' : '50',
            'novalnet_giropay' : '69',
            'novalnet_paypal' : '34',
            'novalnet_przelewy24' : '78',
        }
        return _payment_key_array[_payment_name];
