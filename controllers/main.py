# -*- coding: utf-8 -*-

import pprint, logging, werkzeug
from werkzeug import urls
from odoo import http
from odoo.http import request
from odoo.addons.payment_novalnet.controllers.callback import NovalnetCallback
from odoo.addons.web.controllers.main import ensure_db, Home

_logger = logging.getLogger(__name__)

class NovalnetController(http.Controller):
    _return_url = '/payment/novalnet/return/'
    @http.route([
        '/payment/novalnet/return/',
    ], type='http', auth='public', csrf=False)
    def novalnet_form_feedback(self, **post):        
        _logger.info('Novalnet: entering form_feedback with post data %s', pprint.pformat(post))
        _post_message = post['status_desc'] if 'status_desc' in post else post['status_text']
        _success_status = post['status'] == '100' or (post['status'] == '90' and post['key'] == '34')
        request.env['payment.transaction'].sudo().form_feedback(post, 'novalnet')
        _base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        hash_value = request.env['ir.config_parameter'].sudo().get_param('hash_result')
        if _success_status:
            """ Transaction success redirection """
            return werkzeug.utils.redirect('/payment/process')
        
        else:
            if 'hash2' in post and post['hash2'] != hash_value:
                _post_message = 'While some data has been changed. The hash check failed.'
                
            """ Transaction failure redirection """
            return request.render('payment_novalnet.payment_novalnet_redirect_failure', {
                'return_url': '%s' % urls.url_join(_base_url, 'shop/payment'),
                'novalnet_post_message': _post_message
            })
    
            
    @http.route('/payment/novalnet/callback', type='http', auth="public", methods=['POST', 'GET'], csrf=False)
    def novalnet_callback(self, redirect=None, **post):
        if(request.params.get('db')):
           ensure_db()
           _novalnet_response = NovalnetCallback.novalnet_callback_process(post)
           return werkzeug.utils.escape(_novalnet_response, 200)
        return werkzeug.utils.escape('Database not selected', 200)    
        
    @http.route(['/payment/novalnet/s2s/create_json_3ds'], type='json', auth='public', csrf=False)
    def novalnet_s2s_create_json_3ds(self, verify_validity=False, **kwargs):

        if not kwargs.get('partner_id'):
            kwargs = dict(kwargs, partner_id=request.env.user.partner_id.id)
        token = request.env['payment.acquirer'].browse(int(kwargs.get('acquirer_id'))).s2s_process(kwargs)

        if not token:
            res = {
                'result': False,
            }
            return res

        res = {
            'result': True,
            'id': token.id,
            'short_name': token.short_name,
            '3d_secure': False,
            'verified': False,
        }

        if verify_validity != False:
            token.validate()
            res['verified'] = token.verified

        return res
