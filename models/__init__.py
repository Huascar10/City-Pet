from datetime import datetime, date, timedelta
import json
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from extensions import db, login_manager

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='administrador', nullable=False)  # 'propietario', 'administrador', 'empleado'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    can_authorize_credit = db.Column(db.Boolean, default=True, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_owner(self):
        return self.role == 'propietario'

    @property
    def is_admin(self):
        return self.role in ('propietario', 'administrador')

    @property
    def is_employee(self):
        return self.role == 'empleado'

    @property
    def can_approve_credit_exception(self):
        if not self.is_active:
            return False
        if self.role == 'propietario':
            return True
        if self.role == 'administrador' and self.can_authorize_credit:
            return True
        return False

    @property
    def is_locked(self):
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False

    @property
    def role_label(self):
        roles = {
            'propietario': 'Propietario',
            'administrador': 'Administrador',
            'empleado': 'Empleado'
        }
        return roles.get(self.role, self.role.capitalize())

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'role': self.role,
            'role_label': self.role_label,
            'is_active': self.is_active,
            'can_authorize_credit': self.can_authorize_credit,
            'failed_login_attempts': self.failed_login_attempts,
            'locked_until': self.locked_until.isoformat() if self.locked_until else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class LoginAttempt(db.Model):
    __tablename__ = 'login_attempts'

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(64), nullable=False, index=True)
    username = db.Column(db.String(100), nullable=True, index=True)
    success = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    category = db.Column(db.String(100), default='General', index=True)
    warehouse = db.Column(db.String(100), default='Principal')
    unit = db.Column(db.String(50), default='Unid')
    barcode = db.Column(db.String(100), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    
    purchase_price = db.Column(db.Float, default=0.0, nullable=False)   # Costo unitario
    sale_price = db.Column(db.Float, default=0.0, nullable=False)       # Precio de venta
    current_stock = db.Column(db.Float, default=0.0, nullable=False)    # Existencia calculada
    min_stock = db.Column(db.Float, default=5.0, nullable=False)        # Stock mínimo
    physical_stock = db.Column(db.Float, default=0.0, nullable=False)   # Conteo físico de auditoría
    expiration_date = db.Column(db.Date, nullable=True)                 # Fecha de vencimiento
    
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    supplier = db.relationship('Supplier', backref=db.backref('products', lazy=True))
    movements = db.relationship('InventoryMovement', backref='product', lazy='dynamic')

    __table_args__ = (
        db.CheckConstraint('current_stock >= 0', name='check_non_negative_stock'),
    )

    @property
    def status(self):
        if self.current_stock <= 0:
            return 'Agotada'
        elif self.current_stock < self.min_stock:
            return 'Menor al Minimo'
        return 'Ok'

    @property
    def difference(self):
        return round(self.physical_stock - self.current_stock, 2)

    @property
    def inventory_value(self):
        return round(self.current_stock * self.purchase_price, 2)

    @property
    def potential_revenue(self):
        return round(self.current_stock * self.sale_price, 2)

    @property
    def profit_margin_percent(self):
        if self.sale_price > 0:
            return round(((self.sale_price - self.purchase_price) / self.sale_price) * 100, 1)
        return 0.0

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'category': self.category,
            'warehouse': self.warehouse,
            'unit': self.unit,
            'barcode': self.barcode,
            'description': self.description,
            'image_url': self.image_url,
            'purchase_price': self.purchase_price,
            'sale_price': self.sale_price,
            'current_stock': self.current_stock,
            'min_stock': self.min_stock,
            'physical_stock': self.physical_stock,
            'difference': self.difference,
            'status': self.status,
            'inventory_value': self.inventory_value,
            'expiration_date': self.expiration_date.strftime('%Y-%m-%d') if self.expiration_date else None,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.company_name if self.supplier else None,
            'is_active': self.is_active
        }


class Client(db.Model):
    __tablename__ = 'clients'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    trade_name = db.Column(db.String(250), nullable=True)     # Solo Razón Social
    name = db.Column(db.String(250), nullable=False)           # Nombre completo / Veterinaria
    owner_name = db.Column(db.String(200), nullable=True)      # Propietario
    department = db.Column(db.String(100), nullable=True)      # Managua, etc.
    municipality = db.Column(db.String(100), nullable=True)    # Managua, Mostrador, etc.
    address = db.Column(db.Text, nullable=True)
    ruc = db.Column(db.String(50), nullable=True, index=True)
    phone = db.Column(db.String(50), nullable=True)
    salesperson = db.Column(db.String(100), nullable=True)     # Lenin Montenegro, Asdrubal Zuniga, Mostrador
    registration_number = db.Column(db.String(100), nullable=True) # No. Matricula
    credit_limit = db.Column(db.Float, default=0.0)
    term_code = db.Column(db.String(50), nullable=True)        # NT30
    credit_days = db.Column(db.Integer, default=0)             # 30
    transport = db.Column(db.String(100), nullable=True)
    payment_condition = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales = db.relationship('Sale', backref='client', lazy=True)

    @property
    def pending_invoices(self):
        return [s for s in self.sales if s.status != 'anulada' and s.balance_due > 0.001]

    @property
    def overdue_invoices(self):
        return [s for s in self.pending_invoices if s.is_overdue]

    @property
    def total_debt(self):
        unpaid = [s for s in self.sales if s.status != 'anulada']
        return round(sum(s.balance_due for s in unpaid), 2)

    @property
    def available_credit(self):
        limit = float(self.credit_limit or 0.0)
        return max(0.0, round(limit - self.total_debt, 2))

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'trade_name': self.trade_name,
            'name': self.name,
            'owner_name': self.owner_name,
            'department': self.department,
            'municipality': self.municipality,
            'address': self.address,
            'ruc': self.ruc,
            'phone': self.phone,
            'salesperson': self.salesperson,
            'registration_number': self.registration_number,
            'credit_limit': round(float(self.credit_limit or 0.0), 2),
            'total_debt': self.total_debt,
            'available_credit': self.available_credit,
            'pending_invoices_count': len(self.pending_invoices),
            'overdue_invoices_count': len(self.overdue_invoices),
            'term_code': self.term_code,
            'credit_days': self.credit_days,
            'transport': self.transport,
            'payment_condition': self.payment_condition,
            'notes': self.notes,
            'is_active': self.is_active
        }


class Supplier(db.Model):
    __tablename__ = 'suppliers'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    company_name = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    ruc = db.Column(db.String(50), nullable=True)
    address = db.Column(db.Text, nullable=True)
    supplied_products = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def pending_purchases(self):
        return [p for p in self.purchases if p.status != 'anulada' and p.balance_due > 0.001]

    @property
    def overdue_purchases(self):
        return [p for p in self.pending_purchases if p.is_overdue]

    @property
    def total_debt(self):
        unpaid = [p for p in self.purchases if p.status != 'anulada']
        return round(sum(p.balance_due for p in unpaid), 2)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'company_name': self.company_name,
            'contact_name': self.contact_name,
            'phone': self.phone,
            'email': self.email,
            'ruc': self.ruc,
            'address': self.address,
            'supplied_products': self.supplied_products,
            'notes': self.notes,
            'total_debt': self.total_debt,
            'pending_purchases_count': len(self.pending_purchases),
            'overdue_purchases_count': len(self.overdue_purchases),
            'is_active': self.is_active
        }


class Sale(db.Model):
    __tablename__ = 'sales'

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)
    client_name = db.Column(db.String(250), nullable=False)
    client_ruc = db.Column(db.String(50), nullable=True)
    client_address = db.Column(db.Text, nullable=True)
    client_code = db.Column(db.String(50), nullable=True)
    salesperson = db.Column(db.String(100), nullable=True)
    payment_method = db.Column(db.String(50), default='Efectivo')
    payment_condition = db.Column(db.String(100), default='Contado')
    subtotal = db.Column(db.Float, default=0.0, nullable=False)
    discount_percent = db.Column(db.Float, default=0.0, nullable=False)
    discount_amount = db.Column(db.Float, default=0.0, nullable=False)
    tax_percent = db.Column(db.Float, default=0.0, nullable=False)
    tax_amount = db.Column(db.Float, default=0.0, nullable=False)
    total = db.Column(db.Float, default=0.0, nullable=False)
    paid_amount = db.Column(db.Float, default=0.0, nullable=False)     # Monto abonado/pagado acumulado
    cost_of_sales = db.Column(db.Float, default=0.0, nullable=False)
    due_date = db.Column(db.Date, nullable=True)                      # Fecha de vencimiento
    credit_exception_id = db.Column(db.Integer, nullable=True)        # Si fue autorizada por excepción
    status = db.Column(db.String(20), default='confirmada', nullable=False) # 'confirmada', 'anulada'
    void_reason = db.Column(db.String(255), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    idempotency_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    items = db.relationship('SaleItem', backref='sale', cascade='all, delete-orphan', lazy=True)
    payments = db.relationship('Payment', backref='sale', cascade='all, delete-orphan', lazy=True, order_by='Payment.created_at.desc()')
    credit_exceptions = db.relationship('CreditException', backref='sale', cascade='all, delete-orphan', lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], backref='sales', lazy=True)
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], lazy=True)

    @property
    def receipt(self):
        return Receipt.query.filter_by(related_sale_id=self.id).first()

    @property
    def receipt_id(self):
        r = self.receipt
        return r.id if r else None

    @property
    def is_credit(self):
        cond = (self.payment_condition or '').strip().lower()
        return 'credito' in cond or 'crédito' in cond

    @property
    def balance_due(self):
        if self.status == 'anulada':
            return 0.0
        return max(0.0, round(self.total - (self.paid_amount or 0.0), 2))

    @property
    def is_paid(self):
        return self.balance_due <= 0.001

    @property
    def is_overdue(self):
        if self.status == 'anulada' or self.balance_due <= 0.001:
            return False
        if self.due_date:
            return self.due_date < date.today()
        if self.is_credit and self.created_at:
            days = self.client.credit_days if (self.client and self.client.credit_days) else 30
            return (self.created_at.date() + timedelta(days=days)) < date.today()
        return False

    @property
    def payment_status(self):
        if self.status == 'anulada':
            return 'Anulada'
        if not self.is_credit:
            return 'Pagado'
        if self.balance_due <= 0.001:
            return 'Liquidado'
        if (self.paid_amount or 0.0) > 0.001:
            return 'Abonado'
        return 'Pendiente'

    def to_dict(self):
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'client_id': self.client_id,
            'client_name': self.client_name,
            'client_ruc': self.client_ruc,
            'client_address': self.client_address,
            'client_code': self.client_code,
            'salesperson': self.salesperson,
            'payment_method': self.payment_method,
            'payment_condition': self.payment_condition,
            'is_credit': self.is_credit,
            'subtotal': self.subtotal,
            'discount_percent': self.discount_percent,
            'discount_amount': self.discount_amount,
            'tax_percent': self.tax_percent,
            'tax_amount': self.tax_amount,
            'total': self.total,
            'paid_amount': self.paid_amount,
            'balance_due': self.balance_due,
            'payment_status': self.payment_status,
            'due_date': self.due_date.strftime('%Y-%m-%d') if self.due_date else None,
            'is_overdue': self.is_overdue,
            'credit_exception_id': self.credit_exception_id,
            'cost_of_sales': self.cost_of_sales,
            'status': self.status,
            'receipt_id': self.receipt_id,
            'void_reason': self.void_reason,
            'notes': self.notes,
            'user_id': self.user_id,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'items': [item.to_dict() for item in self.items]
        }


class CreditException(db.Model):
    """Bitácora auditable de autorizaciones de excepción de límite de crédito o facturas vencidas."""
    __tablename__ = 'credit_exceptions'

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id', ondelete='CASCADE'), nullable=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    authorized_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    authorized_by_username = db.Column(db.String(50), nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    credit_limit_snapshot = db.Column(db.Float, default=0.0, nullable=False)
    previous_debt_snapshot = db.Column(db.Float, default=0.0, nullable=False)
    new_credit_amount = db.Column(db.Float, default=0.0, nullable=False)
    excess_amount = db.Column(db.Float, default=0.0, nullable=False)
    had_overdue_invoices = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    client = db.relationship('Client', backref='credit_exceptions', lazy=True)
    authorized_by = db.relationship('User', foreign_keys=[authorized_by_id], lazy=True)
    requested_by = db.relationship('User', foreign_keys=[requested_by_id], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'sale_id': self.sale_id,
            'invoice_number': self.sale.invoice_number if self.sale else None,
            'client_id': self.client_id,
            'client_name': self.client.name if self.client else '',
            'authorized_by_id': self.authorized_by_id,
            'authorized_by_username': self.authorized_by_username,
            'requested_by_id': self.requested_by_id,
            'reason': self.reason,
            'credit_limit_snapshot': self.credit_limit_snapshot,
            'previous_debt_snapshot': self.previous_debt_snapshot,
            'new_credit_amount': self.new_credit_amount,
            'excess_amount': self.excess_amount,
            'had_overdue_invoices': self.had_overdue_invoices,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class SaleItem(db.Model):
    __tablename__ = 'sale_items'

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id', ondelete='CASCADE'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_code_snapshot = db.Column(db.String(50), nullable=False)
    product_name_snapshot = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_price_snapshot = db.Column(db.Float, nullable=False)
    unit_cost_snapshot = db.Column(db.Float, default=0.0, nullable=False)
    discount_percent = db.Column(db.Float, default=0.0, nullable=False)
    discount_amount = db.Column(db.Float, default=0.0, nullable=False)
    total = db.Column(db.Float, nullable=False)

    product = db.relationship('Product', backref='sale_items', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_code': self.product_code_snapshot,
            'product_name': self.product_name_snapshot,
            'quantity': self.quantity,
            'unit_price': self.unit_price_snapshot,
            'unit_cost': self.unit_cost_snapshot,
            'discount_percent': self.discount_percent,
            'discount_amount': self.discount_amount,
            'total': self.total
        }


class Payment(db.Model):
    """Abonos a facturas de ventas a crédito."""
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    payment_number = db.Column(db.String(50), unique=True, nullable=False, index=True) # e.g. ABN-202611-0001
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id', ondelete='CASCADE'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    previous_balance = db.Column(db.Float, nullable=False)
    new_balance = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), default='Efectivo') # Efectivo, Transferencia, Cheque
    reference = db.Column(db.String(100), nullable=True) # Referencia bancaria, cheque, etc.
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='confirmado', nullable=False) # 'confirmado', 'anulado'
    void_reason = db.Column(db.String(255), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id'), nullable=True)
    idempotency_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    client = db.relationship('Client', backref='payments', lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], backref='registered_payments', lazy=True)
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], lazy=True)
    receipt = db.relationship('Receipt', foreign_keys=[receipt_id], backref=db.backref('payment_record', uselist=False), lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'payment_number': self.payment_number,
            'sale_id': self.sale_id,
            'invoice_number': self.sale.invoice_number if self.sale else '',
            'client_id': self.client_id,
            'client_name': self.client.name if self.client else '',
            'amount': self.amount,
            'previous_balance': self.previous_balance,
            'new_balance': self.new_balance,
            'payment_method': self.payment_method,
            'reference': self.reference,
            'notes': self.notes,
            'status': self.status,
            'void_reason': self.void_reason,
            'receipt_id': self.receipt_id,
            'user_id': self.user_id,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class Purchase(db.Model):
    """Compras de mercancía a proveedores."""
    __tablename__ = 'purchases'

    id = db.Column(db.Integer, primary_key=True)
    purchase_number = db.Column(db.String(50), unique=True, nullable=False, index=True) # e.g. COM-202611-0001
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False, index=True)
    supplier_name_snapshot = db.Column(db.String(200), nullable=False)
    supplier_ruc_snapshot = db.Column(db.String(50), nullable=True)
    supplier_invoice_number = db.Column(db.String(100), nullable=True) # Factura/remisión del proveedor
    warehouse = db.Column(db.String(100), default='Principal')
    payment_method = db.Column(db.String(50), default='Efectivo')
    payment_condition = db.Column(db.String(50), default='Contado')
    subtotal = db.Column(db.Float, default=0.0, nullable=False)
    tax_amount = db.Column(db.Float, default=0.0, nullable=False)
    discount_amount = db.Column(db.Float, default=0.0, nullable=False)
    total = db.Column(db.Float, default=0.0, nullable=False)
    paid_amount = db.Column(db.Float, default=0.0, nullable=False)     # Monto pagado acumulado al proveedor
    due_date = db.Column(db.Date, nullable=True)                      # Fecha de vencimiento
    status = db.Column(db.String(20), default='confirmada', nullable=False) # 'confirmada', 'anulada'
    notes = db.Column(db.Text, nullable=True)
    void_reason = db.Column(db.String(255), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id'), nullable=True)
    idempotency_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    supplier = db.relationship('Supplier', backref='purchases', lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], backref='purchases', lazy=True)
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], lazy=True)
    items = db.relationship('PurchaseItem', backref='purchase', cascade='all, delete-orphan', lazy=True)
    payments = db.relationship('PurchasePayment', backref='purchase', cascade='all, delete-orphan', lazy=True, order_by='PurchasePayment.created_at.desc()')
    receipt = db.relationship('Receipt', foreign_keys=[receipt_id], backref=db.backref('purchase_record', uselist=False), lazy=True)

    @property
    def is_credit(self):
        cond = (self.payment_condition or '').strip().lower()
        return 'credito' in cond or 'crédito' in cond

    @property
    def balance_due(self):
        if self.status == 'anulada':
            return 0.0
        return max(0.0, round(self.total - (self.paid_amount or 0.0), 2))

    @property
    def is_paid(self):
        return self.balance_due <= 0.001

    @property
    def is_overdue(self):
        if self.status == 'anulada' or self.balance_due <= 0.001:
            return False
        if self.due_date:
            return self.due_date < date.today()
        return False

    @property
    def payment_status(self):
        if self.status == 'anulada':
            return 'Anulada'
        if not self.is_credit:
            return 'Liquidado'
        if self.balance_due <= 0.001:
            return 'Liquidado'
        if (self.paid_amount or 0.0) > 0.001:
            return 'Abonado'
        return 'Pendiente'

    def to_dict(self):
        return {
            'id': self.id,
            'purchase_number': self.purchase_number,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name_snapshot,
            'supplier_ruc': self.supplier_ruc_snapshot,
            'supplier_invoice_number': self.supplier_invoice_number,
            'warehouse': self.warehouse,
            'payment_method': self.payment_method,
            'payment_condition': self.payment_condition,
            'is_credit': self.is_credit,
            'subtotal': self.subtotal,
            'tax_amount': self.tax_amount,
            'discount_amount': self.discount_amount,
            'total': self.total,
            'paid_amount': self.paid_amount,
            'balance_due': self.balance_due,
            'payment_status': self.payment_status,
            'due_date': self.due_date.strftime('%Y-%m-%d') if self.due_date else None,
            'is_overdue': self.is_overdue,
            'status': self.status,
            'receipt_id': self.receipt_id,
            'void_reason': self.void_reason,
            'notes': self.notes,
            'user_id': self.user_id,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'items': [item.to_dict() for item in self.items]
        }


class PurchaseItem(db.Model):
    __tablename__ = 'purchase_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id', ondelete='CASCADE'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product_code_snapshot = db.Column(db.String(50), nullable=False)
    product_name_snapshot = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    update_product_cost = db.Column(db.Boolean, default=True)

    product = db.relationship('Product', backref='purchase_items', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_code': self.product_code_snapshot,
            'product_name': self.product_name_snapshot,
            'quantity': self.quantity,
            'unit_cost': self.unit_cost,
            'total': self.total,
            'update_product_cost': self.update_product_cost
        }


class PurchasePayment(db.Model):
    """Pagos y abonos a facturas de compras a crédito de proveedores."""
    __tablename__ = 'purchase_payments'

    id = db.Column(db.Integer, primary_key=True)
    payment_number = db.Column(db.String(50), unique=True, nullable=False, index=True) # e.g. PAG-202611-0001
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id', ondelete='CASCADE'), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    previous_balance = db.Column(db.Float, nullable=False)
    new_balance = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), default='Efectivo')
    reference = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='confirmado', nullable=False) # 'confirmado', 'anulado'
    void_reason = db.Column(db.String(255), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id'), nullable=True)
    idempotency_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    supplier = db.relationship('Supplier', backref='purchase_payments', lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], backref='registered_purchase_payments', lazy=True)
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], lazy=True)
    receipt = db.relationship('Receipt', foreign_keys=[receipt_id], backref=db.backref('purchase_payment_record', uselist=False), lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'payment_number': self.payment_number,
            'purchase_id': self.purchase_id,
            'purchase_number': self.purchase.purchase_number if self.purchase else '',
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier.company_name if self.supplier else '',
            'amount': self.amount,
            'previous_balance': self.previous_balance,
            'new_balance': self.new_balance,
            'payment_method': self.payment_method,
            'reference': self.reference,
            'notes': self.notes,
            'status': self.status,
            'void_reason': self.void_reason,
            'receipt_id': self.receipt_id,
            'user_id': self.user_id,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class InventoryMovement(db.Model):
    __tablename__ = 'inventory_movements'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    operation_type = db.Column(db.String(30), nullable=False, index=True)
    # Types: 'Compra', 'Venta', 'Regalias', 'Devolucion_Cliente', 'Devolucion_Proveedor', 'Ajuste_Entrada', 'Ajuste_Salida', 'Danado_Merma', 'Inventario_Inicial'
    quantity = db.Column(db.Float, nullable=False)
    previous_stock = db.Column(db.Float, nullable=False)
    new_stock = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, default=0.0)
    unit_cost = db.Column(db.Float, default=0.0)
    total_value = db.Column(db.Float, default=0.0)
    tax_applied = db.Column(db.String(20), nullable=True)
    discount_percent = db.Column(db.Float, default=0.0)
    discount_amount = db.Column(db.Float, default=0.0)
    payment_condition = db.Column(db.String(50), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id'), nullable=True)
    invoice_number = db.Column(db.String(50), nullable=True)
    salesperson = db.Column(db.String(100), nullable=True)
    warehouse = db.Column(db.String(100), default='Principal')
    reason = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    status = db.Column(db.String(20), default='confirmado') # 'confirmado', 'anulado'
    is_reversal = db.Column(db.Boolean, default=False)
    reversal_of_id = db.Column(db.Integer, db.ForeignKey('inventory_movements.id'), nullable=True)
    void_reason = db.Column(db.String(255), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    client = db.relationship('Client', backref='movements', lazy=True)
    supplier = db.relationship('Supplier', backref='movements', lazy=True)
    purchase = db.relationship('Purchase', backref='inventory_movements', lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], backref='inventory_movements', lazy=True)
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else '',
            'product_name': self.product.name if self.product else '',
            'operation_type': self.operation_type,
            'quantity': self.quantity,
            'previous_stock': self.previous_stock,
            'new_stock': self.new_stock,
            'unit_price': self.unit_price,
            'unit_cost': self.unit_cost,
            'total_value': self.total_value,
            'tax_applied': self.tax_applied,
            'discount_percent': self.discount_percent,
            'discount_amount': self.discount_amount,
            'payment_condition': self.payment_condition,
            'due_date': self.due_date.strftime('%Y-%m-%d') if self.due_date else None,
            'client_id': self.client_id,
            'supplier_id': self.supplier_id,
            'sale_id': self.sale_id,
            'purchase_id': self.purchase_id,
            'invoice_number': self.invoice_number,
            'reason': self.reason,
            'notes': self.notes,
            'status': self.status,
            'is_reversal': self.is_reversal,
            'reversal_of_id': self.reversal_of_id,
            'user_id': self.user_id,
            'user_name': self.user.full_name if self.user else 'Sistema',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class FinancialMovement(db.Model):
    __tablename__ = 'financial_movements'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    movement_type = db.Column(db.String(30), nullable=False, index=True) # 'Ingreso', 'Gasto', 'Ajuste_Caja', 'Devolucion'
    category = db.Column(db.String(100), nullable=False) # 'Venta', 'Compra', 'Abono_Venta', 'Pago_Proveedor', 'Servicios', 'Alquiler', etc.
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), default='Efectivo')
    description = db.Column(db.Text, nullable=False)
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id'), nullable=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=True)
    purchase_payment_id = db.Column(db.Integer, db.ForeignKey('purchase_payments.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date = db.Column(db.Date, default=date.today, nullable=False, index=True)
    
    status = db.Column(db.String(20), default='confirmado') # 'confirmado', 'anulado'
    void_reason = db.Column(db.String(255), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='financial_movements', lazy=True)
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'movement_type': self.movement_type,
            'category': self.category,
            'amount': self.amount,
            'payment_method': self.payment_method,
            'description': self.description,
            'receipt_id': self.receipt_id,
            'sale_id': self.sale_id,
            'purchase_id': self.purchase_id,
            'payment_id': self.payment_id,
            'purchase_payment_id': self.purchase_payment_id,
            'user_id': self.user_id,
            'date': self.date.strftime('%Y-%m-%d') if self.date else None,
            'status': self.status,
            'void_reason': self.void_reason,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'user_name': self.user.full_name if self.user else 'Sistema'
        }


class Receipt(db.Model):
    __tablename__ = 'receipts'

    id = db.Column(db.Integer, primary_key=True)
    receipt_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    receipt_type = db.Column(db.String(30), nullable=False, index=True)
    # Types: 'Venta', 'Compra', 'Abono', 'Pago_Proveedor', 'Entrada_Inventario', 'Salida_Inventario', 'Ingreso', 'Gasto', 'Ajuste', 'Regalia', 'Devolucion'
    related_sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    related_purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=True)
    related_payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=True)
    related_purchase_payment_id = db.Column(db.Integer, db.ForeignKey('purchase_payments.id'), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Snapshot of entity info at time of generation (immutable record)
    client_name_snapshot = db.Column(db.String(250), nullable=True)
    client_ruc_snapshot = db.Column(db.String(50), nullable=True)
    client_address_snapshot = db.Column(db.Text, nullable=True)
    salesperson_snapshot = db.Column(db.String(100), nullable=True)
    client_code_snapshot = db.Column(db.String(50), nullable=True)

    subtotal = db.Column(db.Float, default=0.0)
    discount_amount = db.Column(db.Float, default=0.0)
    tax_amount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0, nullable=False)
    payment_method = db.Column(db.String(50), nullable=True)
    payment_condition = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='confirmado', nullable=False) # 'confirmado', 'anulado'
    notes = db.Column(db.Text, nullable=True)
    void_reason = db.Column(db.String(255), nullable=True)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)

    # Inmutable payload containing all line items and movement details
    payload_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', foreign_keys=[user_id], backref='receipts', lazy=True)
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], lazy=True)
    client = db.relationship('Client', backref='receipts', lazy=True)
    supplier = db.relationship('Supplier', backref='receipts', lazy=True)

    @property
    def payload(self):
        try:
            return json.loads(self.payload_json)
        except Exception:
            return {}

    def to_dict(self):
        return {
            'id': self.id,
            'receipt_number': self.receipt_number,
            'receipt_type': self.receipt_type,
            'related_sale_id': self.related_sale_id,
            'related_purchase_id': self.related_purchase_id,
            'related_payment_id': self.related_payment_id,
            'related_purchase_payment_id': self.related_purchase_payment_id,
            'client_id': self.client_id,
            'supplier_id': self.supplier_id,
            'user_id': self.user_id,
            'client_name': self.client_name_snapshot,
            'client_ruc': self.client_ruc_snapshot,
            'client_address': self.client_address_snapshot,
            'client_code': self.client_code_snapshot,
            'salesperson': self.salesperson_snapshot,
            'subtotal': self.subtotal,
            'discount_amount': self.discount_amount,
            'tax_amount': self.tax_amount,
            'total_amount': self.total_amount,
            'payment_method': self.payment_method,
            'payment_condition': self.payment_condition,
            'status': self.status,
            'notes': self.notes,
            'void_reason': self.void_reason,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'payload': self.payload
        }


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user_name = db.Column(db.String(100), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(50), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'action': self.action,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(200), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_val(cls, key, default=None):
        try:
            setting = db.session.get(cls, key)
            if setting and setting.value is not None:
                return setting.value
        except Exception:
            pass
        return default

    @classmethod
    def set_val(cls, key, value, description=None):
        setting = db.session.get(cls, key)
        if not setting:
            setting = cls(key=key, value=str(value), description=description)
            db.session.add(setting)
        else:
            setting.value = str(value)
            if description:
                setting.description = description
        db.session.commit()
        return setting
