jQuery( document ).ready(function() {
    if(jQuery( 'input[name="vendor"]' ).val() != undefined ) {
			$('#payment_novalnet').on('click', function() {
				// Validation for basic parameters
				if(jQuery( 'input[name="novalnet_validation_message"]' ).val() != undefined && jQuery( 'input[name="novalnet_validation_message"]' ).val() != '') {
					alert(jQuery( 'input[name="novalnet_validation_message"]' ).val());
					return false;
				}
				// Validation for vendor parameters
				if( jQuery( 'input[name="vendor"]' ).val() == '' || jQuery( 'input[name="product"]' ).val() == '' || jQuery( 'input[name="tariff"]' ).val() == '' || jQuery( 'input[name="auth_code"]' ).val() == '' ) {
					alert(jQuery( 'input[name="novalnet_validation_message"]' ).val());
					return false;
				}
				jQuery( 'input[name="novalnet_validation_message"]' ).remove();
			});
	}		
});

