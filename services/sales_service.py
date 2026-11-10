from datetime import datetime, date, timedelta
import json
from flask import current_app
from extensions import db
from models import Product, Client, Sale, SaleItem, FinancialMovement, Receipt, AuditLog, Payment, User, CreditException
from services.inventory_service import InventoryService
from services.telegram_service import TelegramService

class CreditLimitExceededError(ValueError):
    """Raised when a credit sale exceeds the client's available credit or has overdue invoices without authorization."""
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}
        self.evaluation = self.details

class SalesService:
    @staticmethod
    def get_next_invoice_number():
        """Generates the next sequential invoice number (e.g. '0501', '0502' or 'FACT-XXXX')."""
        last_sale = Sale.query.order_by(Sale.id.desc()).first()
        if not last_sale or not last_sale.invoice_number:
            return "0501"
        
        raw_num = last_sale.invoice_number.replace('FACT-', '').strip()
        try:
            num = int(raw_num) + 1
            return f"{num:04d}" if num < 10000 else str(num)
        except ValueError:
            return f"FACT-{last_sale.id + 1:04d}"

    @staticmethod
    def evaluate_client_credit(client, requested_credit_amount):
        """
        Evaluates a client's credit status for a new credit sale.
        Returns a dictionary with full credit diagnostics.
        """
        if not client:
            return {
                'allowed': False,
                'requires_authorization': False,
                'reason': 'Debe seleccionar un cliente registrado para realizar ventas a crédito.',
                'credit_limit': 0.0,
                'current_debt': 0.0,
                'available_credit': 0.0,
                'requested_credit': round(requested_credit_amount, 2),
                'excess_amount': round(requested_credit_amount, 2),
                'overdue_count': 0
            }

        credit_limit = round(float(client.credit_limit or 0.0), 2)
        current_debt = round(float(client.total_debt or 0.0), 2)
        available_credit = max(0.0, round(credit_limit - current_debt, 2))
        requested = round(float(requested_credit_amount or 0.0), 2)
        projected_debt = round(current_debt + requested, 2)
        excess = max(0.0, round(projected_debt - credit_limit, 2))
        overdue_invoices = client.overdue_invoices
        overdue_count = len(overdue_invoices)

        exceeds_limit = projected_debt > (credit_limit + 0.009)
        has_overdue = overdue_count > 0

        reasons = []
        if exceeds_limit:
            reasons.append(
                f"El saldo a financiar (C$ {requested:,.2f}) sumado a la deuda actual (C$ {current_debt:,.2f}) "
                f"supera el límite de crédito autorizado (C$ {credit_limit:,.2f}) por C$ {excess:,.2f}."
            )
        if has_overdue:
            reasons.append(
                f"El cliente presenta {overdue_count} factura(s) vencida(s) pendiente(s) de pago."
            )

        allowed = not exceeds_limit and not has_overdue
        return {
            'allowed': allowed,
            'requires_authorization': (exceeds_limit or has_overdue),
            'exceeds_limit': exceeds_limit,
            'has_overdue': has_overdue,
            'reason': " ".join(reasons) if reasons else "Crédito dentro del límite permitido.",
            'credit_limit': credit_limit,
            'current_debt': current_debt,
            'available_credit': available_credit,
            'requested_credit': requested,
            'projected_debt': projected_debt,
            'excess_amount': excess,
            'overdue_count': overdue_count
        }

    @staticmethod
    def verify_credit_exception_authorization(auth_username, auth_password, auth_reason, current_user_id=None):
        """
        Verifies supervisor credentials and mandatory reason for a credit exception.
        Only 'propietario' or 'administrador' with can_authorize_credit=True can approve.
        Employees can NEVER approve credit exceptions.
        """
        if not auth_reason or len(str(auth_reason).strip()) < 5:
            raise ValueError("Debe ingresar un motivo obligatorio (mínimo 5 caracteres) para autorizar la excepción de crédito.")

        if not auth_password:
            raise ValueError("Se requiere la contraseña de un Propietario o Administrador autorizado para aprobar la excepción.")

        authorizer = None
        if auth_username and str(auth_username).strip():
            authorizer = User.query.filter_by(username=str(auth_username).strip()).first()
        elif current_user_id:
            authorizer = db.session.get(User, int(current_user_id))

        if not authorizer or not authorizer.is_active:
            raise ValueError("Usuario autorizador no válido o cuenta inactiva.")

        if not authorizer.can_approve_credit_exception:
            raise ValueError(
                f"Permiso denegado: El usuario '{authorizer.username}' ({authorizer.role_label}) "
                f"no tiene privilegios para autorizar excepciones de crédito."
            )

        if not authorizer.check_password(str(auth_password)):
            raise ValueError("Credenciales de autorización incorrectas. La contraseña del supervisor no es válida.")

        return authorizer

    @staticmethod
    def generate_preview(sale_data, items_data):
        """Generates a complete simulated preview calculation with watermark and credit status."""
        if not items_data or len(items_data) == 0:
            raise ValueError("Debe incluir al menos un producto para la vista previa.")

        client_id = sale_data.get('client_id')
        client = db.session.get(Client, int(client_id)) if client_id else None
        client_name = sale_data.get('client_name') or (client.name if client else "Cliente Ocasional / Mostrador")
        client_ruc = sale_data.get('client_ruc') or (client.ruc if client else '')
        client_address = sale_data.get('client_address') or (client.address if client else '')
        client_code = sale_data.get('client_code') or (client.code if client else 'CP-GEN')
        salesperson = sale_data.get('salesperson') or (client.salesperson if client else 'Mostrador')
        payment_method = sale_data.get('payment_method', 'Efectivo')
        payment_condition = sale_data.get('payment_condition', 'Contado')
        notes = sale_data.get('notes', '')

        subtotal = 0.0
        total_discount = 0.0
        items_preview = []

        for item in items_data:
            prod_id = item.get('product_id')
            product = db.session.get(Product, int(prod_id)) if prod_id else None
            if not product:
                raise ValueError(f"Producto ID {prod_id} no existe.")

            qty = float(item.get('quantity', 1))
            if qty <= 0:
                raise ValueError(f"La cantidad para '{product.name}' debe ser mayor a 0.")

            unit_price = float(item.get('unit_price', product.sale_price))
            dscto_pct = float(item.get('discount_percent', 0.0))

            line_subtotal = round(qty * unit_price, 2)
            line_dscto = round(line_subtotal * (dscto_pct / 100.0), 2)
            line_total = round(line_subtotal - line_dscto, 2)

            subtotal += line_subtotal
            total_discount += line_dscto

            items_preview.append({
                'code': product.code,
                'name': product.name,
                'quantity': qty,
                'current_stock': product.current_stock,
                'unit_price': unit_price,
                'discount_percent': dscto_pct,
                'discount_amount': line_dscto,
                'total': line_total
            })

        tax_percent = float(sale_data.get('tax_percent', 0.0))
        taxable_base = subtotal - total_discount
        tax_amount = round(taxable_base * (tax_percent / 100.0), 2)
        total_amount = round(taxable_base + tax_amount, 2)

        is_credit = bool(payment_condition and ('credito' in payment_condition.lower() or 'crédito' in payment_condition.lower()))
        if not is_credit:
            initial_payment = total_amount
        else:
            initial_payment = max(0.0, float(sale_data.get('initial_payment', 0.0) or 0.0))
            initial_payment = min(initial_payment, total_amount)
        balance_due = round(total_amount - initial_payment, 2)

        credit_eval = None
        if is_credit and balance_due > 0:
            credit_eval = SalesService.evaluate_client_credit(client, balance_due)

        return {
            'is_preview': True,
            'watermark': 'VISTA PREVIA — NO VÁLIDO COMO FACTURA',
            'simulated_invoice_number': sale_data.get('invoice_number') or SalesService.get_next_invoice_number(),
            'client_name': client_name,
            'client_ruc': client_ruc,
            'client_address': client_address,
            'client_code': client_code,
            'salesperson': salesperson,
            'payment_method': payment_method,
            'payment_condition': payment_condition,
            'is_credit': is_credit,
            'subtotal': round(subtotal, 2),
            'discount_amount': round(total_discount, 2),
            'tax_percent': tax_percent,
            'tax_amount': round(tax_amount, 2),
            'total': round(total_amount, 2),
            'initial_payment': round(initial_payment, 2),
            'balance_due': balance_due,
            'credit_evaluation': credit_eval,
            'notes': notes,
            'items': items_preview,
            'items_count': len(items_preview)
        }

    @staticmethod
    def create_sale(sale_data=None, items_data=None, user_id=None, **kwargs):
        """
        Executes an atomic sale transaction with idempotency, strict stock locking,
        and backend credit limit enforcement with auditable supervisor exception support.
        Supports both create_sale(sale_data, items_data, user_id=...) and keyword arguments.
        """
        if sale_data is None:
            sale_data = {}
        else:
            sale_data = dict(sale_data)

        if 'client_data' in kwargs and isinstance(kwargs['client_data'], dict):
            cd = kwargs.pop('client_data')
            if 'client_id' in cd:
                sale_data.setdefault('client_id', cd['client_id'])
            if 'name' in cd:
                sale_data.setdefault('client_name', cd['name'])
            if 'client_name' in cd:
                sale_data.setdefault('client_name', cd['client_name'])
            if 'ruc' in cd:
                sale_data.setdefault('client_ruc', cd['ruc'])
            if 'address' in cd:
                sale_data.setdefault('client_address', cd['address'])

        if 'credit_authorization' in kwargs and isinstance(kwargs['credit_authorization'], dict):
            ca = kwargs.pop('credit_authorization')
            sale_data.setdefault('auth_username', ca.get('username') or ca.get('auth_username'))
            sale_data.setdefault('auth_password', ca.get('password') or ca.get('auth_password'))
            sale_data.setdefault('auth_reason', ca.get('reason') or ca.get('auth_reason'))

        for k, v in kwargs.items():
            sale_data.setdefault(k, v)

        idempotency_token = sale_data.get('idempotency_token')
        if idempotency_token:
            existing_sale = Sale.query.filter_by(idempotency_token=idempotency_token).first()
            if existing_sale:
                receipt = Receipt.query.filter_by(related_sale_id=existing_sale.id).first()
                return existing_sale, receipt

        if not items_data or len(items_data) == 0:
            raise ValueError("La venta debe contener al menos un producto.")

        # Client resolution with row lock if credit
        client_id = sale_data.get('client_id')
        client = None
        if client_id and str(client_id).strip():
            client = db.session.query(Client).filter_by(id=int(client_id)).with_for_update().first()
        
        client_name = (sale_data.get('client_name') or '').strip()
        if not client_name:
            client_name = client.name if client else "Cliente Ocasional / Mostrador"
            
        client_ruc = sale_data.get('client_ruc') or (client.ruc if client else '')
        client_address = sale_data.get('client_address') or (client.address if client else '')
        client_code = sale_data.get('client_code') or (client.code if client else 'CP-GEN')
        salesperson = sale_data.get('salesperson') or (client.salesperson if client else 'Mostrador')
        payment_method = sale_data.get('payment_method', 'Efectivo')
        payment_condition = sale_data.get('payment_condition', 'Contado')
        notes = sale_data.get('notes', '')
        
        invoice_number = sale_data.get('invoice_number') or SalesService.get_next_invoice_number()

        # Check invoice uniqueness
        existing_sale = Sale.query.filter_by(invoice_number=invoice_number).first()
        if existing_sale:
            invoice_number = SalesService.get_next_invoice_number()

        subtotal = 0.0
        total_discount = 0.0
        total_cost_of_sales = 0.0
        processed_items = []
        stock_alerts = []

        # Validate and prepare items with pessimistic row lock
        for item in items_data:
            prod_id = item.get('product_id')
            product = db.session.query(Product).filter_by(id=int(prod_id)).with_for_update().first() if prod_id else None
            if not product:
                raise ValueError(f"Producto ID {prod_id} no existe.")

            qty = float(item.get('quantity', 1))
            if qty <= 0:
                raise ValueError(f"La cantidad para '{product.name}' debe ser mayor a 0.")

            if product.current_stock < qty:
                raise ValueError(
                    f"Existencias insuficientes para '{product.name}'. "
                    f"Disponibles: {product.current_stock:.2f}, Solicitadas: {qty:.2f}."
                )

            unit_price = float(item.get('unit_price', product.sale_price))
            unit_cost = float(product.purchase_price or 0.0)
            dscto_pct = float(item.get('discount_percent', 0.0) or 0.0)
            if dscto_pct < 0 or dscto_pct > 100:
                raise ValueError(f"Porcentaje de descuento inválido ({dscto_pct}%) para '{product.name}'.")
            
            line_subtotal = round(qty * unit_price, 2)
            line_dscto = round(line_subtotal * (dscto_pct / 100.0), 2)
            line_total = round(line_subtotal - line_dscto, 2)

            subtotal += line_subtotal
            total_discount += line_dscto
            total_cost_of_sales += round(qty * unit_cost, 2)

            processed_items.append({
                'product': product,
                'product_id': product.id,
                'code': product.code,
                'name': product.name,
                'quantity': qty,
                'unit_price': unit_price,
                'unit_cost': unit_cost,
                'discount_percent': dscto_pct,
                'discount_amount': line_dscto,
                'total': line_total
            })

            new_stock = product.current_stock - qty
            if new_stock <= 0:
                stock_alerts.append((product, 'out_stock'))
            elif new_stock < product.min_stock:
                stock_alerts.append((product, 'low_stock'))

        global_dscto_pct = float(sale_data.get('global_discount_percent', 0.0) or 0.0)
        if global_dscto_pct > 0 and total_discount == 0:
            total_discount = round(subtotal * (global_dscto_pct / 100.0), 2)

        tax_percent = float(sale_data.get('tax_percent', 0.0) or 0.0)
        taxable_base = max(0.0, subtotal - total_discount)
        tax_amount = round(taxable_base * (tax_percent / 100.0), 2)
        total_amount = round(taxable_base + tax_amount, 2)

        # Payment & Credit calculations
        is_credit = bool(payment_condition and ('credito' in payment_condition.lower() or 'crédito' in payment_condition.lower()))
        if not is_credit:
            paid_amount = total_amount
            due_date_val = None
        else:
            initial_p = max(0.0, float(sale_data.get('initial_payment', 0.0) or 0.0))
            paid_amount = min(initial_p, total_amount)
            raw_due = sale_data.get('due_date')
            if raw_due:
                if isinstance(raw_due, date):
                    due_date_val = raw_due
                else:
                    try:
                        due_date_val = datetime.strptime(str(raw_due).strip()[:10], '%Y-%m-%d').date()
                    except ValueError:
                        due_date_val = date.today() + timedelta(days=(client.credit_days if client and client.credit_days else 30))
            else:
                credit_days = (client.credit_days if client and client.credit_days and client.credit_days > 0 else 30)
                due_date_val = date.today() + timedelta(days=credit_days)

        credit_balance_due = round(total_amount - paid_amount, 2)

        # STRICT BACKEND CREDIT LIMIT & OVERDUE VALIDATION
        credit_exception_record = None
        if is_credit and credit_balance_due > 0.001:
            if not client:
                raise CreditLimitExceededError(
                    "Para registrar una venta a crédito con saldo pendiente debe seleccionar un cliente registrado en el catálogo.",
                    {'requires_client': True}
                )

            credit_eval = SalesService.evaluate_client_credit(client, credit_balance_due)
            if not credit_eval['allowed']:
                # Check if supervisor authorization was supplied
                auth_username = sale_data.get('auth_username')
                auth_password = sale_data.get('auth_password')
                auth_reason = sale_data.get('auth_reason')

                if not auth_password and not auth_reason:
                    raise CreditLimitExceededError(
                        f"Operación bloqueada por control de crédito: {credit_eval['reason']} "
                        f"Se requiere autorización de un Propietario o Administrador.",
                        credit_eval
                    )

                authorizer = SalesService.verify_credit_exception_authorization(
                    auth_username=auth_username,
                    auth_password=auth_password,
                    auth_reason=auth_reason,
                    current_user_id=user_id
                )

                credit_exception_record = CreditException(
                    client_id=client.id,
                    authorized_by_id=authorizer.id,
                    authorized_by_username=authorizer.username,
                    requested_by_id=user_id,
                    reason=str(auth_reason).strip(),
                    credit_limit_snapshot=credit_eval['credit_limit'],
                    previous_debt_snapshot=credit_eval['current_debt'],
                    new_credit_amount=credit_balance_due,
                    excess_amount=credit_eval['excess_amount'],
                    had_overdue_invoices=credit_eval['has_overdue'],
                    created_at=datetime.utcnow()
                )
                db.session.add(credit_exception_record)
                db.session.flush()

        # 1. Create Sale
        sale = Sale(
            invoice_number=invoice_number,
            client_id=client.id if client else None,
            client_name=client_name,
            client_ruc=client_ruc,
            client_address=client_address,
            client_code=client_code,
            salesperson=salesperson,
            payment_method=payment_method,
            payment_condition=payment_condition,
            subtotal=round(subtotal, 2),
            discount_percent=round(global_dscto_pct, 2),
            discount_amount=round(total_discount, 2),
            tax_percent=round(tax_percent, 2),
            tax_amount=round(tax_amount, 2),
            total=round(total_amount, 2),
            paid_amount=round(paid_amount, 2),
            cost_of_sales=round(total_cost_of_sales, 2),
            due_date=due_date_val,
            credit_exception_id=credit_exception_record.id if credit_exception_record else None,
            status='confirmada',
            idempotency_token=idempotency_token,
            notes=notes,
            user_id=user_id,
            created_at=datetime.utcnow()
        )
        db.session.add(sale)
        db.session.flush() # get sale.id

        if credit_exception_record:
            credit_exception_record.sale_id = sale.id
            audit_exc = AuditLog(
                user_id=credit_exception_record.authorized_by_id,
                user_name=credit_exception_record.authorized_by_username,
                action='AUTHORIZE_CREDIT_EXCEPTION',
                entity_type='CreditException',
                entity_id=str(credit_exception_record.id),
                details=(
                    f"Excepción de crédito autorizada por @{credit_exception_record.authorized_by_username} "
                    f"para Factura #{invoice_number} ({client.name}). "
                    f"Límite: C$ {credit_exception_record.credit_limit_snapshot:,.2f}, "
                    f"Deuda previa: C$ {credit_exception_record.previous_debt_snapshot:,.2f}, "
                    f"Nuevo crédito: C$ {credit_exception_record.new_credit_amount:,.2f}, "
                    f"Exceso autorizado: C$ {credit_exception_record.excess_amount:,.2f}. "
                    f"Motivo: {credit_exception_record.reason}"
                )
            )
            db.session.add(audit_exc)

        # 2. Create Sale Items & Inventory Movements
        items_payload = []
        for it in processed_items:
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=it['product_id'],
                product_code_snapshot=it['code'],
                product_name_snapshot=it['name'],
                quantity=it['quantity'],
                unit_price_snapshot=it['unit_price'],
                unit_cost_snapshot=it['unit_cost'],
                discount_percent=it['discount_percent'],
                discount_amount=it['discount_amount'],
                total=it['total']
            )
            db.session.add(sale_item)

            InventoryService.record_movement(
                product_id=it['product_id'],
                operation_type='Venta',
                quantity=it['quantity'],
                user_id=user_id,
                reason=f"Venta Factura #{invoice_number}",
                notes=f"Cliente: {client_name}",
                client_id=client.id if client else None,
                sale_id=sale.id,
                invoice_number=invoice_number,
                salesperson=salesperson,
                unit_price=it['unit_price'],
                unit_cost=it['unit_cost']
            )

            items_payload.append({
                'code': it['code'],
                'name': it['name'],
                'quantity': it['quantity'],
                'unit_price': it['unit_price'],
                'discount_percent': it['discount_percent'],
                'discount_amount': it['discount_amount'],
                'total': it['total']
            })

        # 3. Financial Movement (ONLY for money actually received!)
        fin_mov = None
        if paid_amount > 0:
            fin_mov = FinancialMovement(
                code=f"FIN-VEN-{sale.id:05d}",
                movement_type='Ingreso',
                category='Venta' if not is_credit else 'Abono_Inicial',
                amount=round(paid_amount, 2),
                payment_method=payment_method,
                description=f"Ingreso por Venta Factura #{invoice_number} - {client_name}" + (" (Contado)" if not is_credit else f" (Abono Inicial de Crédito C$ {paid_amount:,.2f})"),
                sale_id=sale.id,
                user_id=user_id,
                date=datetime.utcnow().date(),
                created_at=datetime.utcnow()
            )
            db.session.add(fin_mov)

        # 4. Inmutable Confirmed Receipt
        amount_received_cash = float(sale_data.get('amount_received', paid_amount) or paid_amount)
        change_given = max(0.0, round(amount_received_cash - paid_amount, 2)) if not is_credit else 0.0

        receipt_payload = {
            'invoice_number': invoice_number,
            'client_name': client_name,
            'client_ruc': client_ruc,
            'client_address': client_address,
            'client_code': client_code,
            'salesperson': salesperson,
            'payment_method': payment_method,
            'payment_condition': payment_condition,
            'subtotal': round(subtotal, 2),
            'discount_amount': round(total_discount, 2),
            'tax_amount': round(tax_amount, 2),
            'tax_percent': tax_percent,
            'total': round(total_amount, 2),
            'paid_amount': round(paid_amount, 2),
            'amount_received': round(amount_received_cash, 2),
            'change_given': change_given,
            'balance_due': round(total_amount - paid_amount, 2),
            'due_date': due_date_val.strftime('%Y-%m-%d') if due_date_val else None,
            'credit_exception_authorized_by': credit_exception_record.authorized_by_username if credit_exception_record else None,
            'notes': notes,
            'date': sale.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'items': items_payload
        }

        receipt = Receipt(
            receipt_number=f"FACT-{invoice_number}",
            receipt_type='Venta',
            related_sale_id=sale.id,
            client_id=client.id if client else None,
            user_id=user_id,
            client_name_snapshot=client_name,
            client_ruc_snapshot=client_ruc,
            client_address_snapshot=client_address,
            salesperson_snapshot=salesperson,
            client_code_snapshot=client_code,
            subtotal=round(subtotal, 2),
            discount_amount=round(total_discount, 2),
            tax_amount=round(tax_amount, 2),
            total_amount=round(total_amount, 2),
            payment_method=payment_method,
            payment_condition=payment_condition,
            status='confirmado',
            notes=notes,
            payload_json=json.dumps(receipt_payload, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.session.add(receipt)
        db.session.flush()

        if fin_mov:
            fin_mov.receipt_id = receipt.id

        # 5. Audit log
        audit = AuditLog(
            user_id=user_id,
            action='CREATE_SALE',
            entity_type='Sale',
            entity_id=str(sale.id),
            details=(
                f"Factura #{invoice_number} emitida a {client_name} por C$ {total_amount:,.2f} "
                f"({payment_condition}, Pagado: C$ {paid_amount:,.2f}, Saldo: C$ {sale.balance_due:,.2f})"
            )
        )
        db.session.add(audit)
        db.session.commit()

        # 6. Async Notifications
        try:
            TelegramService.notify_sale(current_app._get_current_object(), sale, receipt)
            for prod, alert_type in stock_alerts:
                TelegramService.notify_stock_alert(current_app._get_current_object(), prod, alert_type)
        except Exception:
            pass

        return sale, receipt

    @staticmethod
    def void_sale(sale_id, user_id, reason):
        """
        Logically voids a sale with mandatory reason, user signature, and compensatory reversal:
        - Reverses inventory for every sold item via compensatory movements.
        - Reverses financial cashflow for the amount actually paid.
        - Updates status to 'anulada'.
        - Fully audited.
        """
        if not reason or len(reason.strip()) < 5:
            raise ValueError("Debe proporcionar un motivo válido de al menos 5 caracteres para anular la venta.")

        sale = db.session.query(Sale).filter_by(id=sale_id).with_for_update().first()
        if not sale:
            raise ValueError("Venta no encontrada.")
        if sale.status == 'anulada':
            raise ValueError("La venta ya se encuentra anulada.")

        # Compensatory inventory movements (Re-stock products)
        for item in sale.items:
            if item.product_id:
                InventoryService.record_movement(
                    product_id=item.product_id,
                    operation_type='Ajuste_Entrada',
                    quantity=item.quantity,
                    user_id=user_id,
                    reason=f"Anulación Factura #{sale.invoice_number}: {reason}",
                    notes=f"Reingreso compensatorio por venta anulada",
                    client_id=sale.client_id,
                    sale_id=sale.id,
                    invoice_number=sale.invoice_number,
                    unit_price=item.unit_price_snapshot,
                    unit_cost=item.unit_cost_snapshot
                )

        # Reversal of money actually received
        for fm in FinancialMovement.query.filter_by(sale_id=sale.id, movement_type='Ingreso').all():
            fm.status = 'anulado'
            fm.void_reason = reason
            fm.voided_by_id = user_id
            fm.voided_at = datetime.utcnow()

        if sale.paid_amount > 0:
            fin_mov = FinancialMovement(
                code=f"FIN-ANU-{sale.id:05d}",
                movement_type='Gasto',
                category='Devolucion',
                amount=sale.paid_amount,
                payment_method=sale.payment_method,
                description=f"Salida compensatoria por anulación Factura #{sale.invoice_number}. Motivo: {reason}",
                sale_id=sale.id,
                user_id=user_id,
                date=datetime.utcnow().date(),
                created_at=datetime.utcnow()
            )
            db.session.add(fin_mov)

        # Mark any associated payments as voided too
        for p in sale.payments:
            if p.status != 'anulado':
                p.status = 'anulado'
                p.void_reason = f"Venta principal anulada: {reason}"
                p.voided_by_id = user_id
                p.voided_at = datetime.utcnow()

        sale.status = 'anulada'
        sale.void_reason = reason
        sale.voided_by_id = user_id
        sale.voided_at = datetime.utcnow()

        receipt = Receipt.query.filter_by(related_sale_id=sale.id).first()
        if receipt:
            receipt.status = 'anulado'
            receipt.void_reason = reason
            receipt.voided_by_id = user_id
            receipt.voided_at = datetime.utcnow()

        audit = AuditLog(
            user_id=user_id,
            action='VOID_SALE',
            entity_type='Sale',
            entity_id=str(sale.id),
            details=f"Factura #{sale.invoice_number} ANULADA. Motivo: {reason}"
        )
        db.session.add(audit)
        db.session.commit()
        return sale
