from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Supplier, Product, InventoryMovement, Purchase, PurchasePayment, Receipt, AuditLog
from routes.auth import admin_required

suppliers_bp = Blueprint('suppliers', __name__, url_prefix='/suppliers')

@suppliers_bp.route('/')
@login_required
def index():
    search = request.args.get('search', '').strip()
    debt_filter = request.args.get('debt', '').strip()
    query = Supplier.query

    if search:
        query = query.filter(
            db.or_(
                Supplier.company_name.ilike(f"%{search}%"),
                Supplier.contact_name.ilike(f"%{search}%"),
                Supplier.code.ilike(f"%{search}%"),
                Supplier.phone.ilike(f"%{search}%"),
                Supplier.ruc.ilike(f"%{search}%")
            )
        )

    suppliers = query.order_by(Supplier.company_name.asc()).all()
    if debt_filter == 'pending':
        suppliers = [s for s in suppliers if s.total_debt > 0.009]
    elif debt_filter == 'overdue':
        suppliers = [s for s in suppliers if len(s.overdue_purchases) > 0]

    return render_template('suppliers/index.html', suppliers=suppliers, search=search, debt_filter=debt_filter)

@suppliers_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create():
    company_name = request.form.get('company_name', '').strip()
    if not company_name:
        flash("El nombre comercial del proveedor es obligatorio.", "danger")
        return redirect(url_for('suppliers.index'))

    code = request.form.get('code', '').strip()
    if not code:
        last_s = Supplier.query.order_by(Supplier.id.desc()).first()
        next_num = (last_s.id + 1) if last_s else 1
        code = f"PROV-{next_num:03d}"

    if Supplier.query.filter_by(code=code).first():
        flash(f"El código '{code}' ya está en uso.", "danger")
        return redirect(url_for('suppliers.index'))

    contact_name = request.form.get('contact_name', '').strip() or None
    phone = request.form.get('phone', '').strip() or None
    email = request.form.get('email', '').strip() or None
    ruc = request.form.get('ruc', '').strip() or None
    address = request.form.get('address', '').strip() or None
    supplied_products = request.form.get('supplied_products', '').strip() or None
    notes = request.form.get('notes', '').strip() or None

    supplier = Supplier(
        code=code,
        company_name=company_name,
        contact_name=contact_name,
        phone=phone,
        email=email,
        ruc=ruc,
        address=address,
        supplied_products=supplied_products,
        notes=notes,
        is_active=True
    )
    db.session.add(supplier)
    
    audit = AuditLog(
        user_id=current_user.id,
        action='CREATE_SUPPLIER',
        entity_type='Supplier',
        entity_id=str(supplier.code),
        details=f"Proveedor creado: {supplier.company_name}"
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Proveedor '{supplier.company_name}' registrado exitosamente.", "success")
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit(id):
    supplier = Supplier.query.get_or_404(id)
    company_name = request.form.get('company_name', '').strip()
    if not company_name:
        flash("El nombre no puede estar en blanco.", "danger")
        return redirect(url_for('suppliers.index'))

    supplier.company_name = company_name
    supplier.contact_name = request.form.get('contact_name', '').strip() or None
    supplier.phone = request.form.get('phone', '').strip() or None
    supplier.email = request.form.get('email', '').strip() or None
    supplier.ruc = request.form.get('ruc', '').strip() or None
    supplier.address = request.form.get('address', '').strip() or None
    supplier.supplied_products = request.form.get('supplied_products', '').strip() or None
    supplier.notes = request.form.get('notes', '').strip() or None

    audit = AuditLog(
        user_id=current_user.id,
        action='UPDATE_SUPPLIER',
        entity_type='Supplier',
        entity_id=str(supplier.code),
        details=f"Proveedor actualizado: {supplier.company_name}"
    )
    db.session.add(audit)
    db.session.commit()
    flash(f"Proveedor '{supplier.company_name}' actualizado correctamente.", "success")
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/<int:id>/history')
@login_required
def history(id):
    supplier = Supplier.query.get_or_404(id)
    products = Product.query.filter_by(supplier_id=id).order_by(Product.name.asc()).all()
    purchases = Purchase.query.filter_by(supplier_id=id).order_by(Purchase.created_at.desc()).all()
    pending_purchases = [p for p in purchases if p.status == 'completada' and not p.is_paid]
    overdue_purchases = [p for p in pending_purchases if p.is_overdue]
    liquidated_purchases = [p for p in purchases if p.status == 'completada' and p.is_paid]
    supplier_payments = PurchasePayment.query.filter_by(supplier_id=id).order_by(PurchasePayment.created_at.desc()).all()
    movements = InventoryMovement.query.filter_by(supplier_id=id).order_by(InventoryMovement.created_at.desc()).all()

    purchase_ids = [p.id for p in purchases]
    pay_ids = [pm.id for pm in supplier_payments]
    receipts = []
    if purchase_ids or pay_ids:
        filters = []
        if purchase_ids:
            filters.append(Receipt.related_purchase_id.in_(purchase_ids))
        if pay_ids:
            filters.append(Receipt.related_purchase_payment_id.in_(pay_ids))
        receipts = Receipt.query.filter(db.or_(*filters)).order_by(Receipt.created_at.desc()).all()

    return render_template(
        'suppliers/history.html',
        supplier=supplier,
        products=products,
        purchases=purchases,
        pending_purchases=pending_purchases,
        overdue_purchases=overdue_purchases,
        liquidated_purchases=liquidated_purchases,
        supplier_payments=supplier_payments,
        receipts=receipts,
        movements=movements
    )
