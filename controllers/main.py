# -*- coding: utf-8 -*-

import pprint, logging, urlparse, werkzeug

from odoo import http
from odoo.http import request
from odoo.addons.payment_novalnet.controllers.callback import NovalnetCallback
from odoo.addons.web.controllers.main import ensure_db, Home


_logger = logging.getLogger(__name__)


class NovalnetController(http.Controller):

    @http.route([
        '/payment/novalnet/return/',
    ], type='http', auth='public', csrf=False)
    def novalnet_form_feedback(self, **post):
        _logger.info('Novalnet: entering form_feedback with post data %s', pprint.pformat(post))
        _post_message = post['status_desc'] if 'status_desc' in post else post['status_text']
        _success_status = post['status'] == '100' or (post['status'] == '90' and post['key'] == '34')
        _return_url = 'shop/confirmation' if _success_status else 'shop/payment'
        request.env['payment.transaction'].sudo().form_feedback(post, 'novalnet')
        _base_url = request.env['ir.config_parameter'].get_param('web.base.url')
        if _success_status:
            
            """ Transaction success redirection """
            return request.render('payment_novalnet.payment_novalnet_redirect_success', {
                'return_url': '%s' % urlparse.urljoin(_base_url, _return_url),
            })
        else:
            
            """ Transaction failure redirection """
            return request.render('payment_novalnet.payment_novalnet_redirect_failure', {
                'return_url': '%s' % urlparse.urljoin(_base_url, _return_url),
                'novalnet_post_message': _post_message
            })
            
    @http.route('/payment/novalnet/callback', type='http', auth="public", methods=['POST', 'GET'], csrf=False)
    def novalnet_callback(self, redirect=None, **post):
        if(request.params.get('db')):
           request.session.db = request.params.get('db').strip()
           ensure_db()
           _novalnet_response = NovalnetCallback.novalnet_callback_process(post)
           request.session.db = False
           return werkzeug.utils.escape(_novalnet_response, 200)
        return werkzeug.utils.escape('Database not selected', 200)    
