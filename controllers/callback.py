# -*- coding: utf-8 -*-

import re, logging, datetime,smtplib,odoo
import socket

from werkzeug import urls
from odoo import http, tools, SUPERUSER_ID
from odoo.http import request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from smtplib import SMTPException
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)
__version__ = odoo.release.version
class NovalnetCallback(http.Controller):
    """ Zero level payment types """
    _zero_level_payment_type = { 'CREDITCARD', 'INVOICE_START', 'DIRECT_DEBIT_SEPA', 'GUARANTEED_INVOICE', 'GUARANTEED_DIRECT_DEBIT_SEPA', 'PAYPAL', 'ONLINE_TRANSFER', 'IDEAL', 'GIROPAY','PRZELEWY24','EPS', 'CASHPAYMENT'}

    """ First level payment types """
    _first_level_payment_type = {'PRZELEWY24_REFUND', 'RETURN_DEBIT_SEPA', 'REVERSAL', 'CREDITCARD_BOOKBACK', 'CREDITCARD_CHARGEBACK', 'PAYPAL_BOOKBACK', 'REFUND_BY_BANK_TRANSFER_EU','GUARANTEED_INVOICE_BOOKBACK','GUARANTEED_SEPA_BOOKBACK', 'CASHPAYMENT_REFUND'}

    """ Second level payment types """
    _second_level_payment_type = { 'ONLINE_TRANSFER_CREDIT','INVOICE_CREDIT', 'CREDIT_ENTRY_CREDITCARD', 'CREDIT_ENTRY_SEPA', 'DEBT_COLLECTION_SEPA', 'DEBT_COLLECTION_CREDITCARD', 'CASHPAYMENT_CREDIT', 'CREDIT_ENTRY_DE', 'DEBT_COLLECTION_DE'}

    """ Novalnet payments category """
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
            'GUARANTEED_SEPA_BOOKBACK'
        },
        'novalnet_ideal' : {
            'IDEAL',
            'REFUND_BY_BANK_TRANSFER_EU',
            'REVERSAL',
            'ONLINE_TRANSFER_CREDIT',
            'CREDIT_ENTRY_DE',
            'DEBT_COLLECTION_DE'
        },
        'novalnet_instant_bank_transfer' : {
            'ONLINE_TRANSFER',
            'ONLINE_TRANSFER_CREDIT',
            'REFUND_BY_BANK_TRANSFER_EU',
            'REVERSAL',
            'CREDIT_ENTRY_DE',
            'DEBT_COLLECTION_DE'
        },
        'novalnet_giropay' : {
            'GIROPAY',
            'REFUND_BY_BANK_TRANSFER_EU',
            'ONLINE_TRANSFER_CREDIT',
            'REVERSAL',
            'CREDIT_ENTRY_DE',
            'DEBT_COLLECTION_DE'
        },
        'novalnet_paypal' : {
            'PAYPAL',
            'PAYPAL_BOOKBACK',
            'SUBSCRIPTION_STOP',
        },
        'novalnet_prepayment' : {
            'INVOICE_START',
            'INVOICE_CREDIT',
            'SUBSCRIPTION_STOP',
            'REFUND_BY_BANK_TRANSFER_EU'
        },
        'novalnet_invoice' : {
            'INVOICE_START',
            'GUARANTEED_INVOICE',
            'GUARANTEED_INVOICE_BOOKBACK',
            'INVOICE_CREDIT',
            'SUBSCRIPTION_STOP',
            'REFUND_BY_BANK_TRANSFER_EU'
        },
        'novalnet_eps' : {
            'EPS',
            'REFUND_BY_BANK_TRANSFER_EU',
            'ONLINE_TRANSFER_CREDIT',
            'REVERSAL',
            'CREDIT_ENTRY_DE',
            'DEBT_COLLECTION_DE'
        },
        'novalnet_przelewy24' : {
            'PRZELEWY24',
            'PRZELEWY24_REFUND'
        },
        'novalnet_cashpayment' : {
            'CASHPAYMENT',
            'CASHPAYMENT_REFUND',
            'CASHPAYMENT_CREDIT'
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
        },
        'CASHPAYMENT' : {
            '100'
        }
    }

    """ Get server request """
    _get_request = {}

    """ Get Order reference """
    _get_order = {}

    """ Success status """
    _success_status = False

    """ Load Novalnet configuration """

    _novalnet_configuration = False

    """ Novalnet Callback test mode """

    _test_mode = False

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

        """ Check for callback script test mode """
        callback_instance._test_mode = callback_instance._novalnet_configuration.novalnet_callbackscript_test_mode

        """ Check for ip authentication """
        novalnet_response = callback_instance._check_authentication()
        if(novalnet_response):
            return novalnet_response

        """ Check for empty request """
        if not _post_data:
            return callback_instance._display_message('Novalnet callback received. No params passed over!')

        """ Check affiliate process """
        if 'vendor_activation' in _post_data and _post_data['vendor_activation'] == '1':
            return callback_instance._check_affiliate(_post_data)

        """ Get Novalnet server request """
        callback_instance._get_request = callback_instance._get_server_request(_post_data)

        if(type(callback_instance._get_request).__name__ == 'str'):
            return callback_instance._get_request
        
        if ('payment_id' not in callback_instance._get_request or (callback_instance._get_request['payment_id'] != '')) and 'key' in callback_instance._get_request and callback_instance._get_request['key'] != '':
            callback_instance._get_request['payment_id'] = callback_instance._get_request['key']
        
        """ Get order reference for the given tid / order_no """
        callback_instance._get_order = callback_instance._get_order_reference(request.cr)

        if(type(callback_instance._get_order).__name__ == 'str'):
            return callback_instance._get_order
 
        _payment_name = callback_instance._get_order['payment_method_type']
        
        if _payment_name:
            _get_payment_key = callback_instance._get_payment_keys(_payment_name)
            callback_instance._get_request['payment_id'] = _get_payment_key
        

        """ Get payment level """
        _get_payment_level = callback_instance._get_payment_type_level()

        """ Success status for the callback execution """
        callback_instance._success_status = callback_instance._get_request['status'] == '100' and callback_instance._get_request['tid_status'] == '100'

        if _get_payment_level == 0:
            return callback_instance._zero_level_process(request.cr)
        elif _get_payment_level == 1 and callback_instance._success_status:
            return callback_instance._first_level_process(request.cr)
        elif _get_payment_level == 2 and callback_instance._success_status:
            return callback_instance._second_level_process(request.cr)
        elif callback_instance._get_request['payment_type'] == 'SUBSCRIPTION_STOP':
            """ Handling SUBSCRIPTION_STOP PROCESS """
        elif callback_instance._get_request['payment_type'] == 'TRANSACTION_CANCELLATION':
            _comments = '';
            if callback_instance._get_request['payment_type'] in ['GUARANTEED_INVOICE','GUARANTEED_DIRECT_DEBIT_SEPA']:
                _comments = 'This is processed as a guarantee payment'
            _payment_name = callback_instance._get_order['payment_method_type']
            _get_payment_key = callback_instance._get_payment_keys(_payment_name)
            _payment_property = request.env['payment.transaction'].sudo()._get_payment_method(_get_payment_key)
            _comments = request.env['payment.transaction'].sudo()._form_basic_comments(_payment_property['payment_name'], callback_instance._get_request['shop_tid'], callback_instance._get_request['payment_id'],callback_instance._get_request['test_mode'],callback_instance._get_request['tid_status'])
                
            _server_error = callback_instance._get_server_response(callback_instance._get_request);
                
            _comments = '\n\nNovalnet callback received. The transaction has been canceled on %s %s'% (callback_instance._get_request['shop_tid'],datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT))
            """ Update callback comments and order status """
            request.cr.execute('UPDATE payment_transaction SET state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(callback_instance._novalnet_configuration.novalnet_on_hold_cancellation_status, _comments, callback_instance._get_order['order_no']))

            request.cr.execute('UPDATE novalnet_callback SET gateway_status=%s WHERE order_no=%s',(callback_instance._is_valid_digit(callback_instance._get_request['tid_status']), callback_instance._get_order['order_no']))
            request.cr.commit()

            _orginal_order_no = callback_instance._get_order['order_no'].split('-')

            
            """ Update transaction comments and status in sale order note """
            request.cr.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
            request.cr.commit()

            """ Process email """
            callback_instance._send_novalnet_callback_email(_comments,callback_instance._get_request)
            return callback_instance._display_message(_comments,_orginal_order_no[0])    
        else:
            _status       = 'status' if callback_instance._get_request['status'] != 100 else 'tid_status'
            _status_value =  callback_instance._get_request['status'] if callback_instance._get_request['status'] != 100 else callback_instance._get_request['tid_status']
            return callback_instance._display_message('Novalnet callback received. ' + _status + ' (' + _status_value + ') is not valid: Only 100 is allowed')

    """ Validate and get the request
    values from server
    >>> _get_server_request(_server_request)
    array
    """
    def _get_server_request(self, _server_request):
        """ Assign required tid parameter """
        _extra_required_param = ''
        
        if _server_request['payment_type'] not in self._zero_level_payment_type and _server_request['payment_type'] != "TRANSACTION_CANCELLATION":
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

        

        if _server_request['payment_type'] != 'SUBSCRIPTION_STOP' and (_server_request['amount'] == '' or self.valid(_server_request['amount']) or _server_request['amount'] < '0'):
            return self._display_message('Novalnet callback received. The requested amount is not valid')

        for (key, value) in enumerate(['invoice_type','invoice_bankname', 'due_date', 'invoice_bankplace', 'invoice_iban', 'invoice_bic']):
            if value not in _server_request:
                _server_request[value] = ''
        """ Validate payment_type """
        if  'payment_type' not in _server_request or _server_request['payment_type'] != 'TRANSACTION_CANCELLATION' or (_server_request['payment_type'] not in self._first_level_payment_type and _server_request['payment_type'] not in self._second_level_payment_type and _server_request['payment_type'] not in self._zero_level_payment_type):
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
        order_details = _cr_data.execute('SELECT order_no, total_amount, callback_amount, payment_method_type,gateway_status,additional_info from novalnet_callback WHERE reference_tid=%s', (self._get_request['shop_tid'],))
        _fetch_order_details = _cr_data.dictfetchone()

        """ Check for communication failure """
        if not _fetch_order_details and self._get_request['payment_type'] in self._zero_level_payment_type:
            if 'order_no' in self._get_request and self._get_request['order_no'] == '':
                return self._display_message('Novalnet callback received. order number invalid')
            return self._update_initial_payment(_cr_data)

        if self._get_request['payment_type'] not in self._payment_groups[_fetch_order_details['payment_method_type']] and self._get_request['payment_type'] != 'TRANSACTION_CANCELLATION':
            return self._display_message('Novalnet callback received. Payment type mismatched')
            
        """ Check for order number mismatch """
        if 'order_no' in self._get_request and self._get_request['order_no'] != _fetch_order_details['order_no']:
            _comments = self._send_critical_error_mail(_cr_data)
            return self._display_message(_comments)
        return _fetch_order_details
    
    
    def _send_critical_error_mail(self, _cr_data):
        
        if self._get_request['status'] == '100':
            _email_from = self._novalnet_configuration.novalnet_callbackscript_email_from
            _email_subject = 'Critical error on shop system Odoo, order not found for TID: '+ self._get_request['tid']
            _comments = 'Technic team,\n\nPlease evaluate this transaction and contact our Technic team and Backend team at Novalnet.\n\n'
            _comments += 'Merchant ID: '+ self._get_request['vendor_id'] + '\n'
            _comments += 'Project ID: '+ self._get_request['product_id'] + '\n'
            _comments += 'TID: ' + self._get_request['tid'] + '\n'
            _comments += 'TID status: '+ self._get_request['tid_status'] + '\n'
            _comments += 'Order no: '+ self._get_request['order_no'] + '\n'
            _comments += 'Payment type: '+ self._get_request['payment_type'] + '\n'
            _comments += 'E-mail: '+ self._get_request['email'] + '\n'
            _comments += '\n\nRegards,\nNovalnet Team'
        msg = MIMEMultipart()
        msg['From'] = _email_from
        msg['To'] = 'technic@novalnet.de'
        msg['Subject'] = _email_subject
        msg.attach(MIMEText(_comments))
        smtp_session = request.env['ir.mail_server'].connect(mail_server_id= False)
        smtp = smtp_session
        smtp = smtp or self.connect(smtp_server, smtp_port, smtp_user, smtp_password,smtp_encryption, smtp_debug, mail_server_id=mail_server_id)
        smtp.sendmail(_email_from, 'technic@novalnet.de', msg.as_string())
        return _comments
        

    """ Handling communication failure
    >>> _update_initial_payment(_cr_data)
    """
    def _update_initial_payment(self, _cr_data):

        """ Get payment key based on the payment_type """
        _payment_key = self._get_callback_payment_key(self._get_request['payment_type'])
       
        """ Get payment details """
        _payment_property = request.env['payment.transaction'].sudo()._get_payment_method(_payment_key)

        """ Form basic comments """
        _comments = request.env['payment.transaction'].sudo()._form_basic_comments(_payment_property['payment_name'], self._get_request['tid'], self._get_request['payment_id'],self._get_request['test_mode'], self._get_request['tid_status'])

        _orginal_order_no = self._get_request['order_no'].split('-')
        
        _base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        _url = '%s' % urls.url_join(_base_url, '')        
        
        
        """ Check for succes transaction """
        if self._get_request['tid_status'] in self._success_code[self._get_request['payment_type']]:

            """ Assign order status """
            if _payment_key in ['33','49','50','69']:
                _order_status = self._novalnet_configuration.novalnet_completion_order_status
                
            _callback_amount = self._get_request['amount']

            """ Process invoice payments """
            if _payment_key == '27':

                """ Process pending payment """
                _callback_amount = 0
                _order_status = self._novalnet_configuration.novalnet_completion_order_status
                _amount_in_cents = self._get_request['amount']
                _callback_paid_amount = float(self._get_request['amount'])/100.0
                self._get_request['amount'] = ('%.2f' % _callback_paid_amount)
                _comments =  request.env['payment.transaction'].sudo()._form_bank_comments(self._get_request, self._novalnet_configuration, self._get_request['order_no'],True)
                self._get_request['amount'] = _amount_in_cents
            
            elif _payment_key in ['34','78'] and self._get_request['tid_status'] in ['90','85','86'] :
                 """ Process pending payment """
                 _callback_amount = 0
                 _order_status = self._novalnet_configuration.novalnet_pending_order_status

            if _order_status == 'done':
                request.env['payment.transaction'].sudo()._set_transaction_done()
                request.env['payment.transaction'].sudo().execute_callback()
            elif _order_status == 'pending':
                request.env['payment.transaction'].sudo()._set_transaction_pending()

            """ Insert the values in novalnet callback """
            _cr_data.execute('INSERT INTO novalnet_callback (order_no, callback_amount, total_amount, reference_tid, callback_tid, callback_log, payment_method_type, gateway_status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (self._get_request['order_no'], _callback_amount, self._get_request['amount'], self._get_request['tid'], self._get_request['tid'], _url, _payment_property['payment_method_type'], self._get_request['status']))
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
        self._send_novalnet_callback_email(_comments,self._get_request)
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
        elif self._get_request['payment_type'] == 'PRZELEWY24' and self._get_order['gateway_status'] == 86:
            _callback_paid_amount = float(self._get_request['amount'])/100.0
            _amount_formated = ('%.2f' % _callback_paid_amount)
            """ Forming callback comments """
            _comments= '\n\nNovalnet Callback Script executed successfully for the TID: %s with amount %s %s on %s.' % (self._get_request['tid'], _amount_formated, self._get_request['currency'], datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT))

            """ Update callback comments and order status """
            _cr_data.execute('UPDATE payment_transaction SET state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(self._novalnet_configuration.novalnet_completion_order_status, _comments, self._get_order['order_no']))

            """ Update callback amount """
            _cr_data.execute('UPDATE novalnet_callback SET callback_amount=%s WHERE order_no=%s',(self._is_valid_digit(self._get_order['callback_amount']) + self._is_valid_digit(self._get_request['amount']), self._get_order['order_no']))
            _cr_data.commit()

            _orginal_order_no = self._get_order['order_no'].split('-')

            if self._novalnet_configuration.novalnet_completion_order_status == 'done':

                """ Update transaction comments in sale order note """
                _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s), state=%s WHERE name=%s', (_comments, 'sale', _orginal_order_no[0]))
                _cr_data.commit()
            else:

                """ Update transaction comments and status in sale order note """
                _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                _cr_data.commit()

            """ Process email """
            self._send_novalnet_callback_email(_comments,self._get_request)
            return self._display_message(_comments,_orginal_order_no[0])
        
        elif self._get_request['payment_type'] in ['GUARANTEED_INVOICE','GUARANTEED_DIRECT_DEBIT_SEPA','INVOICE_START','DIRECT_DEBIT_SEPA','CREDITCARD','PAYPAL'] and self._get_order['gateway_status'] in [75,91,99,98,85,90]:
            if self._get_request['tid_status'] =='100' and self._get_request['status'] == '100':
                _payment_name = self._get_order['payment_method_type']
                _get_payment_key = self._get_payment_keys(_payment_name)
                self._get_request['payment_id'] = _get_payment_key
                
                if self._get_request['payment_type'] in ['GUARANTEED_INVOICE','GUARANTEED_DIRECT_DEBIT_SEPA','INVOICE_START']:
                    _payment_property = request.env['payment.transaction'].sudo()._get_payment_method(_get_payment_key)
                    _comments = request.env['payment.transaction'].sudo()._form_basic_comments(_payment_property['payment_name'], self._get_request['shop_tid'], self._get_request['payment_id'],self._get_request['test_mode'], self._get_request['tid_status'])
                if self._get_request['tid_status'] in ['91','99'] and self._get_order['gateway_status'] == 75:
                   _order_status = self._novalnet_configuration.novalnet_on_hold_confirmation_status if self._get_request['payment_type'] == 'GUARANTEED_INVOICE' else self._novalnet_configuration.novalnet_on_hold_confirmation_status
                   _comments=  '\n\nNovalnet callback received. The transaction status has been changed from pending to on hold for the TID: %s on %s.' % (self._get_request['shop_tid'], datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)) + _comments 
                elif self._get_request['tid_status'] == '100' and self._get_order['gateway_status'] in [75,91,99,98,85,90]:
                    _order_status = self._novalnet_configuration.novalnet_completion_order_status
                        
                    _comments = '\n\nNovalnet callback received. The transaction has been confirmed on %s\n'% (datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT))
            
                    if self._get_request['payment_type'] in ['GUARANTEED_INVOICE','INVOICE_START'] and self._get_order['gateway_status'] in [75,91]:
                        _comments = _comments + request.env['payment.transaction'].sudo()._form_bank_comments(self._get_request, self._novalnet_configuration,self._get_request['order_no'],True)                            

                """ Update callback comments and order status """
                _cr_data.execute('UPDATE payment_transaction SET state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(_order_status, _comments, self._get_order['order_no']))

                _cr_data.execute('UPDATE novalnet_callback SET gateway_status=%s WHERE order_no=%s',(self._is_valid_digit(self._get_request['tid_status']), self._get_order['order_no']))
                _cr_data.commit()
                _orginal_order_no = self._get_order['order_no'].split('-')
                if self._novalnet_configuration.novalnet_completion_order_status == 'done':
                    """ Update transaction comments in sale order note """
                    _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s), state=%s WHERE name=%s', (_comments, 'sale', _orginal_order_no[0]))
                    _cr_data.commit()
                else:

                    """ Update transaction comments and status in sale order note """
                    _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                    _cr_data.commit()

                """ Process email """
                self._send_novalnet_callback_email(_comments,self._get_request,self._get_order['order_no'])
                return self._display_message(_comments,_orginal_order_no[0])
            else: 
                _comments = '';
                if self._get_request['payment_type'] in ['GUARANTEED_INVOICE','GUARANTEED_DIRECT_DEBIT_SEPA']:
                    _comments = 'This is processed as a guarantee payment'
                _payment_name = self._get_order['payment_method_type']
                _get_payment_key = self._get_payment_keys(_payment_name)
                _payment_property = request.env['payment.transaction'].sudo()._get_payment_method(_get_payment_key)
                _comments = request.env['payment.transaction'].sudo()._form_basic_comments(_payment_property['payment_name'], self._get_request['shop_tid'], self._get_request['payment_id'], self._get_request['test_mode'])
                    
                _server_error = self._get_server_response(self._get_request);
                    
                _comments = '\n\nNovalnet callback received. The transaction has been canceled on %s %s'% (self._get_request['shop_tid'],datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT))
                """ Update callback comments and order status """
                _cr_data.execute('UPDATE payment_transaction SET state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(self._novalnet_configuration.novalnet_on_hold_cancellation_status, _comments, self._get_order['order_no']))

                _cr_data.execute('UPDATE novalnet_callback SET gateway_status=%s WHERE order_no=%s',(self._is_valid_digit(self._get_request['tid_status']), self._get_order['order_no']))
                _cr_data.commit()

                _orginal_order_no = self._get_order['order_no'].split('-')

                if self._novalnet_configuration.novalnet_completion_order_status == 'done':
                    """ Update transaction comments in sale order note """
                    _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s), state=%s WHERE name=%s', (_comments, 'sale', _orginal_order_no[0]))
                    _cr_data.commit()
                else:

                    """ Update transaction comments and status in sale order note """
                    _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
                    _cr_data.commit()

                """ Process email """
                self._send_novalnet_callback_email(_comments,self._get_request)
                return self._display_message(_comments,_orginal_order_no[0])                
        else:
            return self._display_message('Novalnet Callbackscript received. Payment type is not applicable for this process!')
    """
    >>> Get Server Error Message
    """
    def _get_server_response(self,_response):
        if _response['status_message'] != '':
            return _response['status_message']
        elif _response['status_text'] != '':
            return _response['status_text']
        elif _response['status_desc'] != '':
            return _response['status_desc']
        else:
            return 'Payment was not successful. An error occurred.'

    """ First level process
    based on the payment type
    >>> _first_level_process(_cr_data)
    """
    def _first_level_process(self, _cr_data):

        """ DO THE STEPS TO UPDATE THE STATUS OF THE ORDER OR THE USER AND NOTE THAT THE PAYMENT WAS RECLAIMED FROM USER """
        """ Forming callback comments """
        _callback_paid_amount = float(self._get_request['amount'])/100.0
        _amount_formated = ('%.2f' % _callback_paid_amount)
        _comments = '\n\nNovalnet callback received. Refund/Bookback executed successfully for the TID: %s amount: %s %s on %s. The subsequent TID: %s.' % (self._get_request['tid_payment'], _amount_formated, self._get_request['currency'], datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT), self._get_request['tid']) if self._get_request['payment_type'] in ['PAYPAL_BOOKBACK', 'CREDITCARD_BOOKBACK','PRZELEWY24_REFUND', 'REFUND_BY_BANK_TRANSFER_EU','GUARANTEED_INVOICE_BOOKBACK','GUARANTEED_SEPA_BOOKBACK','CASHPAYMENT_REFUND'] else '\n\nNovalnet callback received. Chargeback executed successfully for the TID: %s amount: %s %s on %s. The subsequent TID: %s.' % (self._get_request['tid_payment'], _amount_formated, self._get_request['currency'], datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT), self._get_request['tid'])

        """ Update callback comments and order status """
        _cr_data.execute('UPDATE payment_transaction SET state_message=CONCAT(state_message, %s) WHERE reference=%s',(_comments, self._get_order['order_no']))
        _cr_data.commit()

        _orginal_order_no = self._get_order['order_no'].split('-')
        
        """ Update transaction comments in sale order note """
        _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
        _cr_data.commit()

        """ Process email """
        self._send_novalnet_callback_email(_comments,self._get_request)
        return self._display_message(_comments,_orginal_order_no[0])

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
            _comments = '\n\nNovalnet Callback Script executed successfully for the TID: %s with amount %s %s on %s. Please refer PAID transaction in our Novalnet Merchant Administration with the TID: %s' % (self._get_request['tid_payment'], _amount_formated, self._get_request['currency'], datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT), self._get_request['tid'])

            """ Calculate paid amount """
            _paid_amount = self._is_valid_digit(self._get_order['callback_amount']) + self._is_valid_digit(self._get_request['amount'])

            _orginal_order_no = self._get_order['order_no'].split('-')

            """ Update callback amount """
            _cr_data.execute('UPDATE novalnet_callback SET callback_amount=%s, callback_tid=%s WHERE order_no=%s',(_paid_amount, self._get_request['tid'], self._get_order['order_no']))
            _cr_data.commit()

            """ Calculate fully paid amount """
            if _paid_amount >= self._is_valid_digit(self._get_order['total_amount']) and self._get_request['payment_type'] in ['INVOICE_CREDIT','CASHPAYMENT_CREDIT']:

                _payment_name = self._get_order['payment_method_type']
                _callback_status = self._novalnet_configuration.novalnet_callback_order_status                
                
                if _payment_name in ['novalnet_invoice','novalnet_prepayment']:
                    _invoice_type = 'invoice' if _payment_name == 'novalnet_invoice' else 'prepayment'
                    _payment_property = request.env['payment.transaction'].sudo()._invoice_type(_invoice_type)
                else:
                    _get_payment_key = self._get_payment_keys(_payment_name)
                    _payment_property = request.env['payment.transaction'].sudo()._get_payment_method(_get_payment_key)                    
                
                
                """ Update Transaction comments without bank details """
                _cr_data.execute('UPDATE payment_transaction SET state=%s, state_message=CONCAT(state_message, %s) WHERE reference=%s',(_callback_status, _comments, self._get_order['order_no']))
                _cr_data.commit()
                
                """ Update transaction comments in sale order note """
                _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s), state=%s WHERE name=%s', (_comments, 'sale', _orginal_order_no[0]))
                _cr_data.commit()

                """ Process email """
                self._send_novalnet_callback_email(_comments,self._get_request)
                return self._display_message(_comments,_orginal_order_no[0])

            """ Update Callback comments """
            _cr_data.execute('UPDATE payment_transaction SET state_message=CONCAT(state_message, %s) WHERE reference=%s',(_comments, self._get_order['order_no']))
            _cr_data.commit()
            
            """ Update transaction comments in sale order note """
            _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
            _cr_data.commit()

            """ Process email """
            self._send_novalnet_callback_email(_comments,self._get_request)
            return self._display_message(_comments,_orginal_order_no[0])
        elif self._is_valid_digit(self._get_order['callback_amount']) == self._is_valid_digit(self._get_order['total_amount']) and self._get_request['payment_type'] in ['DEBT_COLLECTION_SEPA','DEBT_COLLECTION_CREDITCARD','CREDIT_ENTRY_SEPA','CREDIT_ENTRY_CREDITCARD','CREDIT_ENTRY_DE','DEBT_COLLECTION_DE']:
               _callback_paid_amount = float(self._get_request['amount'])/100.0
               _amount_formated = ('%.2f' % _callback_paid_amount)
               _orginal_order_no = self._get_order['order_no'].split('-')
               _comments = '\n\nNovalnet Callback Script executed successfully for the TID: %s with amount %s %s on %s. Please refer PAID transaction in our Novalnet Merchant Administration with the TID: %s' % (self._get_request['tid_payment'], _amount_formated, self._get_request['currency'], datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT), self._get_request['tid'])
               _cr_data.execute('UPDATE payment_transaction SET state_message=CONCAT(state_message, %s) WHERE reference=%s',(_comments, self._get_order['order_no']))
               _cr_data.execute('UPDATE sale_order SET note=CONCAT(note, %s) WHERE name=%s', (_comments, _orginal_order_no[0]))
               _cr_data.commit()
               self._send_novalnet_callback_email(_comments,self._get_request)
               return self._display_message(_comments,_orginal_order_no[0])
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
            'novalnet_cashpayment' : '59',
            'novalnet_giropay' : '69',
            'novalnet_paypal' : '34',
            'novalnet_przelewy24' : '78',
        }
        for (key, value) in self._payment_groups.iteritems():
             for (keys, values) in enumerate(value):
                if self._get_request['payment_type'] in value:
                    return _payment_key_array[key]        

    def _get_callback_payment_key(self, _payment_type):
        
        if _payment_type == 'IDEAL':
            return '49'
        elif _payment_type == 'EPS':
            return '50'
        elif _payment_type == 'ONLINE_TRANSFER':
            return '33'
        elif _payment_type == 'GIROPAY':
            return '69'
        elif _payment_type == 'PAYPAL':
            return '34'
        elif _payment_type == 'PRZELEWY24':
            return '78'


    """ Check for authentication
    >>> _check_authentication()
    """
    def _check_authentication(self):
        real_host_ip = socket.gethostbyname("pay-nn.de")
        if real_host_ip == '':
            return self._display_message('Novalnet HOST IP missing')
        
        remote_address = self._get_client_ip()
        if remote_address != real_host_ip  and not self._test_mode:
            remote_address = str(remote_address).replace(',','')
            return self._display_message('Novalnet callback received. Unauthorised access from the IP ' + remote_address)
        return False

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
    def _send_novalnet_callback_email(self, _message,_request = '', _order_no= ''):
        """ Check for callback email """
        if self._novalnet_configuration.novalnet_callbackscript_email and self._novalnet_configuration.novalnet_callbackscript_email_from != '' and self._novalnet_configuration.novalnet_callbackscript_email_to != '' :                       
            _email_from = self._novalnet_configuration.novalnet_callbackscript_email_from
            _email_to   = tools.email_split_and_format(self._novalnet_configuration.novalnet_callbackscript_email_to)
            _email_to   = ''.join(_email_to) 
            _email_bcc  = tools.email_split_and_format(self._novalnet_configuration.novalnet_callbackscript_email_bcc)
            if _request['payment_id'] in ['40','41']:
                _subject    = 'Order Confirmation - Your Order %s with has been confirmed!'%(_order_no)
                _body = self._gurantee_mail_generation(_request)
            else:
                _subject    = 'Novalnet odoo callback script'
                _body = _message
            msg = MIMEMultipart()
            msg['From'] = _email_from
            msg['To'] = ''.join(_email_to)
            msg['Bcc'] = ''.join(_email_bcc)
            msg['Subject'] = _subject
            msg.attach(MIMEText(_body))
            rcpt = ''.join(_email_bcc) .split(",") + [_email_to]

            """ Send email """
            if __version__ in ['11.0','12.0','13.0']:
                smtp_session = request.env['ir.mail_server'].connect(mail_server_id= False)
                smtp = smtp_session
                smtp = smtp or self.connect(smtp_server, smtp_port, smtp_user, smtp_password,smtp_encryption, smtp_debug, mail_server_id=mail_server_id)
                smtp.sendmail(_email_from, rcpt, msg.as_string())

    """
    >>> Generate guarantee mail
    """
    def _gurantee_mail_generation(self,_request):
        return '&lt;body style="background:#F6F6F6; font-family:Verdana, Arial, Helvetica, sans-serif; font-size:14px; margin:0; padding:0;"&gt;&lt;div style="width:55%;height:auto;margin: 0 auto;background:rgb(247, 247, 247);border: 2px solid rgb(223, 216, 216);border-radius: 5px;box-shadow: 1px 7px 10px -2px #ccc;"&gt;&lt;div style="min-height: 300px;padding:20px;"&gt;&lt;b&gt;Dear Mr./Ms./Mrs.&lt;/b&gt;'._request['first_name']+_request['last_name']+'\n\nWe are pleased to inform you that your order has been confirmed.\n\n&lt;b&gt;Payment Information:&lt;/b&gt;\n'+_datas['comments']+'&lt;/div&gt;&lt;div style="width:100%;height:20px;background:#00669D;"&gt;&lt;/div&gt;&lt;/div&gt;&lt;/body&gt;'

    """ Show callback process messages
    >>> _display_message(_message)
    """
    def _display_message(self, _message,order_no= ''):
        _logger.info(_message)
        if order_no != '':
           return 'message='+_message + '&order_no='+order_no
        else:
           return 'message='+ _message

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
            'novalnet_cashpayment' : '59',
            'novalnet_przelewy24' : '78',
        }
        return _payment_key_array[_payment_name];
