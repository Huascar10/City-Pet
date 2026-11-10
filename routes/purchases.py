import json
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Purchase, PurchasePayment, Product, Supplier, Receipt
from services.purchase_service import PurchaseService
from services.payment_service import PaymentService
from routes.auth import admin_required

purchases_bp = Blueprint('purchases', __name__, url_prefix='/purchases')

@purchases_bp.route('/')
@login_required
@admin_required
def index():
    status = request.args.get('status', '').strip()
    payment_status = request.args.get('payment_status', '').strip()
    supplier_id = request.args.get('supplier_id', '').strip()
    search = request.args.get('search', '').strip()

    query = Purchase.query

    if status:
        query = query.filter_by(status=status)
    if supplier_id:
        query = query.filter_by(supplier_id=int(supplier_id))
    if search:
        query = query.filter(
            db.or_(
                Purchase.purchase_number.ilike(f"%{search}%"),
                Purchase.supplier_name_snapshot.ilike(f"%{search}%"),
                Purchase.supplier_invoice_number.ilike(f"%{search}%")
            )
        )

    purchases = query.order_by(Purchase.created_at.desc()).limit(150).all()
    if payment_status:
        purchases = [p for p in purchases if p.payment_status.lower() == payment_status.lower()]

    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name.asc()).all()

    all_active_purchases = Purchase.query.filter(Purchase.status != 'anulada').all()
    pending_purchases = [p for p in all_active_purchases if p.balance_due > 0.001]
    total_payable = round(sum(p.balance_due for p in pending_purchases), 2)
    overdue_count = sum(1 for p in pending_purchases if p.is_overdue)
    recent_supplier_payments = PurchasePayment.query.order_by(PurchasePayment.created_at.desc()).limit(50).all()

    return render_template(
        'purchases/index.html',
        purchases=purchases,
        pending_purchases=pending_purchases,
        recent_supplier_payments=recent_supplier_payments,
        total_payable=total_payable,
        overdue_count=overdue_count,
        suppliers=suppliers,
        status=status,
        payment_status=payment_status,
        supplier_id=supplier_id,
        search=search
    )

@purchases_bp.route('/new')
@login_required
@admin_required
def new():
    next_number = PurchaseService.get_next_purchase_number()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name.asc()).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
    return render_template(
        'purchases/create.html',
        next_number=next_number,
        suppliers=suppliers,
        products=products
    )

@purchases_bp.route('/preview', methods=['POST'])
@login_required
@admin_required
def preview():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    purchase_data = {
        'supplier_id': data.get('supplier_id'),
        'supplier_invoice_number': data.get('supplier_invoice_number'),
        'payment_method': data.get('payment_method', 'Efectivo'),
        'payment_condition': data.get('payment_condition', 'Contado'),
        'initial_payment': float(data.get('initial_payment', 0.0) or 0.0),
        'due_date': data.get('due_date'),
        'warehouse': data.get('warehouse', 'Principal'),
        'tax_amount': float(data.get('tax_amount', 0.0) or 0.0),
        'discount_amount': float(data.get('discount_amount', 0.0) or 0.0),
        'purchase_number': data.get('purchase_number')
    }

    items_data = data.get('items', [])
    if isinstance(items_data, str):
        items_data = json.loads(items_data)

    try:
        preview_data = PurchaseService.generate_preview(purchase_data, items_data)
        return jsonify({'success': True, 'preview': preview_data})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f"Error en vista previa de compra: {str(e)}"}), 500

@purchases_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    purchase_data = {
        'supplier_id': data.get('supplier_id'),
        'supplier_invoice_number': data.get('supplier_invoice_number'),
        'payment_method': data.get('payment_method', 'Efectivo'),
        'payment_condition': data.get('payment_condition', 'Contado'),
        'initial_payment': float(data.get('initial_payment', 0.0) or 0.0),
        'due_date': data.get('due_date'),
        'warehouse': data.get('warehouse', 'Principal'),
        'notes': data.get('notes'),
        'tax_amount': float(data.get('tax_amount', 0.0) or 0.0),
        'discount_amount': float(data.get('discount_amount', 0.0) or 0.0),
        'purchase_number': data.get('purchase_number'),
        'idempotency_token': data.get('idempotency_token')
    }

    items_data = data.get('items', [])
    if isinstance(items_data, str):
        items_data = json.loads(items_data)

    try:
        purchase, receipt = PurchaseService.create_purchase(purchase_data, items_data, current_user.id)
        if request.is_json:
            return jsonify({
                'success': True,
                'purchase_id': purchase.id,
                'receipt_id': receipt.id if receipt else None,
                'purchase_number': purchase.purchase_number,
                'redirect_url': url_for('purchases.show', id=purchase.id)
            })
        flash(f"¡Compra #{purchase.purchase_number} registrada correctamente! Inventario y cuentas actualizadas.", "success")
        return redirect(url_for('purchases.show', id=purchase.id))
    except ValueError as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(str(e), "danger")
        return redirect(url_for('purchases.new'))
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': f"Error en el servidor: {str(e)}"}), 500
        flash(f"Error registrando la compra: {str(e)}", "danger")
        return redirect(url_for('purchases.new'))

@purchases_bp.route('/<int:id>')
@login_required
@admin_required
def show(id):
    purchase = Purchase.query.get_or_404(id)
    return render_template('purchases/show.html', purchase=purchase)

@purchases_bp.route('/<int:id>/payment', methods=['POST'])
@login_required
@admin_required
def register_payment(id):
    """Registers a partial or full payment towards a credit purchase (Accounts Payable)."""
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
        supp_payment, receipt = PaymentService.register_supplier_payment(
            purchase_id=id,
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
                'payment_id': supp_payment.id,
                'receipt_id': receipt.id,
                'new_balance': supp_payment.new_balance,
                'redirect_url': url_for('receipts.view_receipt', id=receipt.id)
            })
        flash(
            f"Pago a proveedor de C$ {supp_payment.amount:,.2f} registrado con éxito. "
            f"Nuevo saldo pendiente: C$ {supp_payment.new_balance:,.2f}",
            "success"
        )
        return redirect(url_for('receipts.view_receipt', id=receipt.id))
    except ValueError as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(str(e), "danger")
        return redirect(request.referrer or url_for('purchases.show', id=id))
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f"Error al registrar pago a proveedor: {str(e)}", "danger")
        return redirect(request.referrer or url_for('purchases.show', id=id))

@purchases_bp.route('/payment/<int:id>/void', methods=['POST'])
@login_required
@admin_required
def void_payment(id):
    reason = request.form.get('reason', '').strip()
    try:
        sp = PaymentService.void_supplier_payment(id, current_user.id, reason)
        flash(f"Pago a proveedor #{sp.payment_number} anulado correctamente.", "info")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al anular pago a proveedor: {str(e)}", "danger")
    return redirect(request.referrer or url_for('purchases.index'))

@purchases_bp.route('/<int:id>/void', methods=['POST'])
@login_required
@admin_required
def void(id):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Debe especificar un motivo válido de al menos 5 caracteres para anular la compra.", "warning")
        return redirect(url_for('purchases.show', id=id))

    try:
        purchase = PurchaseService.void_purchase(id, current_user.id, reason)
        flash(f"Compra #{purchase.purchase_number} anulada correctamente. Stock deducido y finanzas compensadas.", "info")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al anular la compra: {str(e)}", "danger")

    return redirect(url_for('purchases.index'))
