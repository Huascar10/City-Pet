from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Client, Sale, Payment, Receipt, CreditException, InventoryMovement, AuditLog
from routes.auth import admin_required

clients_bp = Blueprint('clients', __name__, url_prefix='/clients')

@clients_bp.route('/')
@login_required
def index():
    search = request.args.get('search', '').strip()
    dept = request.args.get('department', '').strip()
    salesperson = request.args.get('salesperson', '').strip()
    debt_filter = request.args.get('debt_filter', '').strip()

    query = Client.query

    if search:
        query = query.filter(
            db.or_(
                Client.name.ilike(f"%{search}%"),
                Client.trade_name.ilike(f"%{search}%"),
                Client.code.ilike(f"%{search}%"),
                Client.ruc.ilike(f"%{search}%"),
                Client.phone.ilike(f"%{search}%")
            )
        )
    if dept:
        query = query.filter_by(department=dept)
    if salesperson:
        query = query.filter(Client.salesperson.ilike(f"%{salesperson}%"))

    clients = query.order_by(Client.code.asc()).limit(350).all()

    if debt_filter == 'con_deuda':
        clients = [c for c in clients if c.total_debt > 0.001]
    elif debt_filter == 'vencidas':
        clients = [c for c in clients if len(c.overdue_invoices) > 0]

    departments = [d[0] for d in db.session.query(Client.department).distinct().filter(Client.department != None).all() if d[0]]
    salespersons = [s[0] for s in db.session.query(Client.salesperson).distinct().filter(Client.salesperson != None).all() if s[0]]

    total_receivable = round(sum(c.total_debt for c in clients), 2)

    return render_template(
        'clients/index.html',
        clients=clients,
        departments=departments,
        salespersons=salespersons,
        search=search,
        selected_dept=dept,
        selected_salesperson=salesperson,
        debt_filter=debt_filter,
        total_receivable=total_receivable
    )

@clients_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create():
    name = request.form.get('name', '').strip()
    trade_name = request.form.get('trade_name', '').strip() or None
    if not name and trade_name:
        name = trade_name
    if not name:
        flash("El nombre o razón social del cliente es obligatorio.", "danger")
        return redirect(url_for('clients.index'))

    code = request.form.get('code', '').strip()
    if not code:
        last_c = Client.query.order_by(Client.id.desc()).first()
        next_num = (last_c.id + 1) if last_c else 1
        code = f"CP-C{next_num:04d}"

    if Client.query.filter_by(code=code).first():
        flash(f"El código de cliente '{code}' ya está en uso.", "danger")
        return redirect(url_for('clients.index'))

    owner_name = request.form.get('owner_name', '').strip() or None
    dept = request.form.get('department', 'MANAGUA').strip()
    muni = request.form.get('municipality', '').strip()
    address = request.form.get('address', '').strip()
    ruc = request.form.get('ruc', '').strip() or None
    phone = request.form.get('phone', '').strip()
    salesperson = request.form.get('salesperson', '').strip()
    matricula = request.form.get('registration_number', '').strip()
    payment_condition = request.form.get('payment_condition', 'Contado').strip()
    notes = request.form.get('notes', '').strip() or None
    
    try: credit_limit = max(0.0, float(request.form.get('credit_limit') or 0.0))
    except ValueError: credit_limit = 0.0

    term_code = request.form.get('term_code', 'NT30').strip()
    try: credit_days = max(0, int(request.form.get('credit_days') or 30))
    except ValueError: credit_days = 30

    client = Client(
        code=code,
        trade_name=trade_name or name,
        name=name,
        owner_name=owner_name,
        department=dept,
        municipality=muni,
        address=address,
        ruc=ruc,
        phone=phone,
        salesperson=salesperson,
        registration_number=matricula,
        credit_limit=credit_limit,
        term_code=term_code,
        credit_days=credit_days,
        payment_condition=payment_condition,
        notes=notes,
        is_active=True
    )
    db.session.add(client)
    
    audit = AuditLog(
        user_id=current_user.id,
        action='CREATE_CLIENT',
        entity_type='Client',
        entity_id=str(client.code),
        details=f"Cliente registrado: {client.code} - {client.name} (Límite C$ {credit_limit:,.2f})"
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Cliente '{client.name}' ({client.code}) guardado correctamente.", "success")
    return redirect(url_for('clients.index'))

@clients_bp.route('/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit(id):
    client = Client.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    trade_name = request.form.get('trade_name', '').strip() or None
    if not name and trade_name:
        name = trade_name
    if not name:
        flash("El nombre no puede estar en blanco.", "danger")
        return redirect(url_for('clients.index'))

    client.name = name
    client.trade_name = trade_name or name
    client.owner_name = request.form.get('owner_name', '').strip() or None
    client.department = request.form.get('department', '').strip()
    client.municipality = request.form.get('municipality', '').strip()
    client.address = request.form.get('address', '').strip()
    client.ruc = request.form.get('ruc', '').strip() or None
    client.phone = request.form.get('phone', '').strip()
    client.salesperson = request.form.get('salesperson', '').strip()
    client.registration_number = request.form.get('registration_number', '').strip()
    if 'payment_condition' in request.form:
        client.payment_condition = request.form.get('payment_condition', '').strip()
    if 'notes' in request.form:
        client.notes = request.form.get('notes', '').strip() or None
    
    try: client.credit_limit = max(0.0, float(request.form.get('credit_limit') or 0.0))
    except ValueError: pass

    client.term_code = request.form.get('term_code', client.term_code or 'NT30').strip()
    try: client.credit_days = max(0, int(request.form.get('credit_days') or 0))
    except ValueError: pass

    db.session.commit()
    flash(f"Información de '{client.name}' actualizada con éxito.", "success")
    return redirect(request.referrer or url_for('clients.index'))

@clients_bp.route('/<int:id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_status(id):
    client = Client.query.get_or_404(id)
    client.is_active = not client.is_active
    action_text = "activado" if client.is_active else "desactivado"
    
    audit = AuditLog(
        user_id=current_user.id,
        action='TOGGLE_CLIENT_STATUS',
        entity_type='Client',
        entity_id=str(client.code),
        details=f"Cliente {client.code} ({client.name}) {action_text}"
    )
    db.session.add(audit)
    db.session.commit()
    flash(f"Cliente '{client.name}' ha sido {action_text}.", "info")
    return redirect(url_for('clients.index'))

@clients_bp.route('/<int:id>/history')
@login_required
def history(id):
    client = Client.query.get_or_404(id)
    sales = Sale.query.filter_by(client_id=id).order_by(Sale.created_at.desc()).all()
    pending_sales = [s for s in sales if s.status != 'anulada' and s.balance_due > 0.001]
    overdue_sales = [s for s in pending_sales if s.is_overdue]
    liquidated_sales = [s for s in sales if s.status != 'anulada' and s.is_credit and s.balance_due <= 0.001]
    payments = Payment.query.filter_by(client_id=id).order_by(Payment.created_at.desc()).all()
    receipts = Receipt.query.filter_by(client_id=id).order_by(Receipt.created_at.desc()).all()
    credit_exceptions = CreditException.query.filter_by(client_id=id).order_by(CreditException.created_at.desc()).all()
    movements = InventoryMovement.query.filter_by(client_id=id).order_by(InventoryMovement.created_at.desc()).limit(100).all()

    return render_template(
        'clients/history.html',
        client=client,
        sales=sales,
        pending_sales=pending_sales,
        overdue_sales=overdue_sales,
        liquidated_sales=liquidated_sales,
        payments=payments,
        receipts=receipts,
        credit_exceptions=credit_exceptions,
        movements=movements
    )

@clients_bp.route('/api/search')
@login_required
def api_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    clients = Client.query.filter(
        Client.is_active == True,
        db.or_(
            Client.name.ilike(f"%{q}%"),
            Client.trade_name.ilike(f"%{q}%"),
            Client.code.ilike(f"%{q}%"),
            Client.ruc.ilike(f"%{q}%"),
            Client.phone.ilike(f"%{q}%")
        )
    ).limit(15).all()

    return jsonify([c.to_dict() for c in clients])
