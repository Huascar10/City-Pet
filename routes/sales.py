import json
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Sale, Product, Client, Receipt, Payment, CreditException
from services.sales_service import SalesService, CreditLimitExceededError
from services.payment_service import PaymentService
from routes.auth import admin_required

sales_bp = Blueprint('sales', __name__, url_prefix='/sales')

@sales_bp.route('/')
@login_required
def index():
    status = request.args.get('status', '').strip()
    payment_status = request.args.get('payment_status', '').strip()
    search = request.args.get('search', '').strip()

    query = Sale.query

    if status:
        query = query.filter_by(status=status)
    if search:
        query = query.filter(
            db.or_(
                Sale.invoice_number.ilike(f"%{search}%"),
                Sale.client_name.ilike(f"%{search}%"),
                Sale.salesperson.ilike(f"%{search}%")
            )
        )

    sales = query.order_by(Sale.created_at.desc()).limit(200).all()

    if payment_status:
        sales = [s for s in sales if s.payment_status.lower() == payment_status.lower()]

    credit_sales_pending = [s for s in Sale.query.filter(Sale.status != 'anulada').all() if s.balance_due > 0.001]
    total_receivable = round(sum(s.balance_due for s in credit_sales_pending), 2)

    return render_template(
        'sales/index.html',
        sales=sales,
        status=status,
        payment_status=payment_status,
        search=search,
        total_receivable=total_receivable,
        pending_count=len(credit_sales_pending)
    )

@sales_bp.route('/pos')
@login_required
def pos():
    next_invoice = SalesService.get_next_invoice_number()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
    salespersons = [
        'Lenin Montenegro', 'Asdrubal Zuniga', 'Mostrador', 'Mario Alberto Chamorro'
    ]
    return render_template(
        'sales/pos.html',
        next_invoice=next_invoice,
        clients=clients,
        products=products,
        salespersons=salespersons
    )

@sales_bp.route('/preview', methods=['POST'])
@login_required
def preview():
    """Generates real-time invoice preview before confirming transaction."""
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    sale_data = {
        'client_id': data.get('client_id'),
        'client_name': data.get('client_name'),
        'client_ruc': data.get('client_ruc'),
        'client_address': data.get('client_address'),
        'client_code': data.get('client_code'),
        'salesperson': data.get('salesperson'),
        'payment_method': data.get('payment_method', 'Efectivo'),
        'payment_condition': data.get('payment_condition', 'Contado'),
        'invoice_number': data.get('invoice_number'),
        'notes': data.get('notes'),
        'tax_percent': float(data.get('tax_percent', 0.0) or 0.0),
        'initial_payment': float(data.get('initial_payment', 0.0) or 0.0),
        'due_date': data.get('due_date')
    }

    items_data = data.get('items', [])
    if isinstance(items_data, str):
        items_data = json.loads(items_data)

    try:
        preview_data = SalesService.generate_preview(sale_data, items_data)
        return jsonify({'success': True, 'preview': preview_data})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f"Error generando vista previa: {str(e)}"}), 500

@sales_bp.route('/create', methods=['POST'])
@login_required
def create():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    sale_data = {
        'client_id': data.get('client_id'),
        'client_name': data.get('client_name'),
        'client_ruc': data.get('client_ruc'),
        'client_address': data.get('client_address'),
        'client_code': data.get('client_code'),
        'salesperson': data.get('salesperson'),
        'payment_method': data.get('payment_method', 'Efectivo'),
        'payment_condition': data.get('payment_condition', 'Contado'),
        'invoice_number': data.get('invoice_number'),
        'idempotency_token': data.get('idempotency_token'),
        'initial_payment': float(data.get('initial_payment', 0.0) or 0.0),
        'amount_received': float(data.get('amount_received', 0.0) or 0.0),
        'global_discount_percent': float(data.get('global_discount_percent', 0.0) or 0.0),
        'due_date': data.get('due_date'),
        'auth_username': data.get('auth_username'),
        'auth_password': data.get('auth_password'),
        'auth_reason': data.get('auth_reason'),
        'notes': data.get('notes'),
        'tax_percent': float(data.get('tax_percent', 0.0) or 0.0)
    }

    items_data = data.get('items', [])
    if isinstance(items_data, str):
        items_data = json.loads(items_data)

    try:
        sale, receipt = SalesService.create_sale(sale_data, items_data, current_user.id)
        if request.is_json:
            return jsonify({
                'success': True,
                'sale_id': sale.id,
                'receipt_id': receipt.id,
                'invoice_number': sale.invoice_number,
                'redirect_url': url_for('receipts.view_receipt', id=receipt.id)
            })
        flash(f"¡Venta Factura #{sale.invoice_number} completada con éxito!", "success")
        return redirect(url_for('receipts.view_receipt', id=receipt.id))
    except CreditLimitExceededError as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({
                'success': False,
                'error': str(e),
                'requires_authorization': True,
                'credit_details': e.details
            }), 400
        flash(str(e), "danger")
        return redirect(url_for('sales.pos'))
    except ValueError as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(str(e), "danger")
        return redirect(url_for('sales.pos'))
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': f"Error en el servidor: {str(e)}"}), 500
        flash(f"Error procesando la venta: {str(e)}", "danger")
        return redirect(url_for('sales.pos'))

@sales_bp.route('/<int:id>/void', methods=['POST'])
@login_required
@admin_required
def void(id):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Debe especificar un motivo válido para anular la venta.", "warning")
        return redirect(url_for('sales.index'))

    try:
        sale = SalesService.void_sale(id, current_user.id, reason)
        flash(f"Factura #{sale.invoice_number} anulada correctamente. Existencias restauradas y caja compensada.", "info")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al anular la factura: {str(e)}", "danger")

    return redirect(url_for('sales.index'))

@sales_bp.route('/<int:id>/abono', methods=['POST'])
@login_required
def create_abono(id):
    """Registers a partial or full payment on a credit invoice."""
    if request.is_json:
        payload = request.get_json()
        amount = payload.get('amount')
        payment_method = payload.get('payment_method', 'Efectivo')
        reference = payload.get('reference')
        notes = payload.get('notes')
        idempotency_token = payload.get('idempotency_token')
    else:
        amount = request.form.get('amount')
        payment_method = request.form.get('payment_method') or 'Efectivo'
        reference = request.form.get('reference')
        notes = request.form.get('notes')
        idempotency_token = request.form.get('idempotency_token')

    try:
        payment, receipt = PaymentService.register_abono(
            sale_id=id,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            user_id=current_user.id,
            idempotency_token=idempotency_token
        )
        if request.is_json:
            return jsonify({
                'success': True,
                'payment_id': payment.id,
                'receipt_id': receipt.id,
                'new_balance': payment.new_balance,
                'redirect_url': url_for('receipts.view_receipt', id=receipt.id)
            })
        flash(f"Abono de C$ {payment.amount:,.2f} registrado con éxito. Nuevo saldo: C$ {payment.new_balance:,.2f}", "success")
        return redirect(url_for('receipts.view_receipt', id=receipt.id))
    except ValueError as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(str(e), "danger")
        return redirect(request.referrer or url_for('sales.abonos_list'))
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error registrando el abono: {str(e)}", "danger")
        return redirect(request.referrer or url_for('sales.abonos_list'))

@sales_bp.route('/abonos/<int:id>/void', methods=['POST'])
@login_required
@admin_required
def void_abono(id):
    reason = request.form.get('reason', '').strip()
    try:
        payment = PaymentService.void_abono(id, current_user.id, reason)
        flash(f"Abono #{payment.payment_number} anulado correctamente.", "info")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al anular abono: {str(e)}", "danger")
    return redirect(request.referrer or url_for('sales.abonos_list'))

@sales_bp.route('/abonos')
@login_required
def abonos_list():
    """Lists all credit sales, pending accounts receivable, and registered abonos."""
    credit_sales = Sale.query.filter(
        Sale.status != 'anulada',
        db.or_(
            Sale.payment_condition.ilike('%credito%'),
            Sale.payment_condition.ilike('%crédito%')
        )
    ).order_by(Sale.created_at.desc()).all()

    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(100).all()
    credit_exceptions = CreditException.query.order_by(CreditException.created_at.desc()).limit(50).all()
    total_receivable = round(sum(s.balance_due for s in credit_sales), 2)
    overdue_count = sum(1 for s in credit_sales if s.is_overdue)

    return render_template(
        'sales/abonos.html',
        credit_sales=credit_sales,
        recent_payments=recent_payments,
        credit_exceptions=credit_exceptions,
        total_receivable=total_receivable,
        overdue_count=overdue_count
    )

@sales_bp.route('/<int:id>')
@login_required
def detail(id):
    sale = Sale.query.get_or_404(id)
    receipt = sale.receipt
    if not receipt:
        from routes.receipts import resolve_receipt_or_404
        receipt = resolve_receipt_or_404(sale.id)
    return redirect(url_for('receipts.view_receipt', id=receipt.id))

@sales_bp.route('/invoice/<path:invoice_number>')
@login_required
def view_by_invoice(invoice_number):
    return redirect(url_for('receipts.view_invoice', invoice_number=invoice_number))
