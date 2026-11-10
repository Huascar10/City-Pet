from datetime import datetime, date, timedelta
import json
from flask import current_app
from extensions import db
from models import Product, Supplier, Purchase, PurchaseItem, PurchasePayment, FinancialMovement, Receipt, AuditLog
from services.inventory_service import InventoryService
from services.telegram_service import TelegramService

class PurchaseService:
    @staticmethod
    def get_next_purchase_number():
        """Generates consecutive purchase number e.g. COM-202611-0001"""
        now = datetime.utcnow()
        prefix = f"COM-{now.strftime('%Y%m')}-"
        last = Purchase.query.filter(Purchase.purchase_number.like(f"{prefix}%")).order_by(Purchase.id.desc()).first()
        if not last:
            return f"{prefix}0001"
        try:
            seq = int(last.purchase_number.split('-')[-1]) + 1
            return f"{prefix}{seq:04d}"
        except Exception:
            return f"{prefix}{last.id + 1:04d}"

    @staticmethod
    def generate_preview(purchase_data, items_data):
        """Simulates purchase calculation before recording."""
        if not items_data or len(items_data) == 0:
            raise ValueError("Debe incluir al menos un producto en la compra.")

        supplier_id = purchase_data.get('supplier_id')
        supplier = db.session.get(Supplier, int(supplier_id)) if supplier_id else None
        if not supplier:
            raise ValueError("Debe seleccionar un proveedor válido.")

        subtotal = 0.0
        items_preview = []

        for item in items_data:
            prod_id = item.get('product_id')
            product = db.session.get(Product, int(prod_id)) if prod_id else None
            if not product:
                raise ValueError(f"Producto ID {prod_id} no existe.")

            qty = float(item.get('quantity', 1))
            if qty <= 0:
                raise ValueError(f"La cantidad para '{product.name}' debe ser mayor a 0.")

            unit_cost = float(item.get('unit_cost', product.purchase_price))
            if unit_cost < 0:
                raise ValueError(f"El costo para '{product.name}' no puede ser negativo.")

            line_total = round(qty * unit_cost, 2)
            subtotal += line_total

            items_preview.append({
                'code': product.code,
                'name': product.name,
                'current_stock': product.current_stock,
                'new_stock_projected': product.current_stock + qty,
                'quantity': qty,
                'current_cost': product.purchase_price,
                'new_unit_cost': unit_cost,
                'total': line_total
            })

        tax_amount = float(purchase_data.get('tax_amount', 0.0) or 0.0)
        discount_amount = float(purchase_data.get('discount_amount', 0.0) or 0.0)
        total = round(subtotal + tax_amount - discount_amount, 2)

        payment_condition = purchase_data.get('payment_condition', 'Contado')
        is_credit = bool(payment_condition and ('credito' in payment_condition.lower() or 'crédito' in payment_condition.lower()))
        if not is_credit:
            initial_payment = total
        else:
            initial_payment = max(0.0, float(purchase_data.get('initial_payment', 0.0) or 0.0))
            initial_payment = min(initial_payment, total)
        balance_due = round(total - initial_payment, 2)

        return {
            'is_preview': True,
            'watermark': 'VISTA PREVIA — COMPRA NO CONFIRMADA',
            'purchase_number': purchase_data.get('purchase_number') or PurchaseService.get_next_purchase_number(),
            'supplier_name': supplier.company_name,
            'supplier_ruc': supplier.ruc,
            'supplier_invoice_number': purchase_data.get('supplier_invoice_number', ''),
            'payment_method': purchase_data.get('payment_method', 'Efectivo'),
            'payment_condition': payment_condition,
            'is_credit': is_credit,
            'subtotal': round(subtotal, 2),
            'tax_amount': round(tax_amount, 2),
            'discount_amount': round(discount_amount, 2),
            'total': total,
            'initial_payment': round(initial_payment, 2),
            'balance_due': balance_due,
            'due_date': purchase_data.get('due_date'),
            'items': items_preview,
            'items_count': len(items_preview)
        }

    @staticmethod
    def create_purchase(purchase_data=None, items_data=None, user_id=None, **kwargs):
        """
        Executes an atomic supplier purchase with Accounts Payable support:
        1. Checks idempotency.
        2. Validates supplier & item lines.
        3. Creates Purchase and PurchaseItems with paid_amount and due_date.
        4. Updates product stock and optionally purchase_price.
        5. Records InventoryMovement (Compra).
        6. Records FinancialMovement (Gasto) ONLY for the amount actually paid initially!
           (If credit purchase with $0 initial payment, $0 cash outflow is recorded).
        7. Records immutable Receipt (Compra).
        8. Logs audit entry and sends optional Telegram notification.
        """
        if purchase_data is None:
            purchase_data = {}
        else:
            purchase_data = dict(purchase_data)

        for k, v in kwargs.items():
            purchase_data.setdefault(k, v)

        idempotency_token = purchase_data.get('idempotency_token')
        if idempotency_token:
            existing = Purchase.query.filter_by(idempotency_token=idempotency_token).first()
            if existing:
                receipt = Receipt.query.filter_by(related_purchase_id=existing.id).first()
                return existing, receipt

        if not items_data or len(items_data) == 0:
            raise ValueError("Debe incluir al menos un producto en la compra.")

        supplier_id = purchase_data.get('supplier_id')
        supplier = db.session.get(Supplier, int(supplier_id)) if supplier_id else None
        if not supplier:
            raise ValueError("Proveedor no encontrado.")

        purchase_number = purchase_data.get('purchase_number') or PurchaseService.get_next_purchase_number()
        existing = Purchase.query.filter_by(purchase_number=purchase_number).first()
        if existing:
            purchase_number = PurchaseService.get_next_purchase_number()

        subtotal = 0.0
        processed_items = []

        for item in items_data:
            prod_id = item.get('product_id')
            product = db.session.query(Product).filter_by(id=int(prod_id)).with_for_update().first() if prod_id else None
            if not product:
                raise ValueError(f"Producto ID {prod_id} no existe.")

            qty = float(item.get('quantity', 1))
            if qty <= 0:
                raise ValueError(f"La cantidad para '{product.name}' debe ser mayor a 0.")

            unit_cost = float(item.get('unit_cost', product.purchase_price))
            if unit_cost < 0:
                raise ValueError(f"El costo para '{product.name}' no puede ser negativo.")

            line_total = round(qty * unit_cost, 2)
            subtotal += line_total
            update_cost = bool(item.get('update_product_cost', True))

            processed_items.append({
                'product': product,
                'quantity': qty,
                'unit_cost': unit_cost,
                'line_total': line_total,
                'update_cost': update_cost
            })

        tax_amount = float(purchase_data.get('tax_amount', 0.0) or 0.0)
        discount_amount = float(purchase_data.get('discount_amount', 0.0) or 0.0)
        total_amount = round(subtotal + tax_amount - discount_amount, 2)
        if total_amount < 0:
            raise ValueError("El total de la compra no puede ser negativo.")

        payment_method = purchase_data.get('payment_method', 'Efectivo')
        payment_condition = purchase_data.get('payment_condition', 'Contado')
        notes = purchase_data.get('notes', '')
        supplier_invoice = purchase_data.get('supplier_invoice_number', '')

        is_credit = bool(payment_condition and ('credito' in payment_condition.lower() or 'crédito' in payment_condition.lower()))
        if not is_credit:
            paid_amount = total_amount
            due_date_val = None
        else:
            initial_p = max(0.0, float(purchase_data.get('initial_payment', 0.0) or 0.0))
            if initial_p > total_amount + 0.01:
                raise ValueError(f"El pago inicial (C$ {initial_p:,.2f}) no puede superar el total de la compra (C$ {total_amount:,.2f}).")
            paid_amount = min(initial_p, total_amount)
            raw_due = purchase_data.get('due_date')
            if raw_due:
                if isinstance(raw_due, date):
                    due_date_val = raw_due
                else:
                    try:
                        due_date_val = datetime.strptime(str(raw_due).strip()[:10], '%Y-%m-%d').date()
                    except ValueError:
                        due_date_val = date.today() + timedelta(days=30)
            else:
                due_date_val = date.today() + timedelta(days=30)

        # 1. Purchase header
        purchase = Purchase(
            purchase_number=purchase_number,
            supplier_id=supplier.id,
            supplier_name_snapshot=supplier.company_name,
            supplier_ruc_snapshot=supplier.ruc,
            supplier_invoice_number=supplier_invoice,
            warehouse=purchase_data.get('warehouse', 'Principal'),
            payment_method=payment_method,
            payment_condition=payment_condition,
            subtotal=round(subtotal, 2),
            tax_amount=round(tax_amount, 2),
            discount_amount=round(discount_amount, 2),
            total=total_amount,
            paid_amount=round(paid_amount, 2),
            due_date=due_date_val,
            status='confirmada',
            idempotency_token=idempotency_token,
            notes=notes,
            user_id=user_id,
            created_at=datetime.utcnow()
        )
        db.session.add(purchase)
        db.session.flush()

        # 2. Items, stock update, and inventory movement
        items_payload = []
        for it in processed_items:
            prod = it['product']
            p_item = PurchaseItem(
                purchase_id=purchase.id,
                product_id=prod.id,
                product_code_snapshot=prod.code,
                product_name_snapshot=prod.name,
                quantity=it['quantity'],
                unit_cost=it['unit_cost'],
                total=it['line_total'],
                update_product_cost=it['update_cost']
            )
            db.session.add(p_item)

            # Update product purchase price if selected
            if it['update_cost'] and it['unit_cost'] > 0:
                prod.purchase_price = it['unit_cost']

            # Record Inventory Movement (Stock Inflow)
            mov = InventoryService.record_movement(
                product_id=prod.id,
                operation_type='Compra',
                quantity=it['quantity'],
                user_id=user_id,
                reason=f"Compra #{purchase_number} a {supplier.company_name}",
                notes=f"Factura Prov: {supplier_invoice}" if supplier_invoice else "",
                supplier_id=supplier.id,
                invoice_number=supplier_invoice or purchase_number,
                unit_cost=it['unit_cost']
            )
            mov.purchase_id = purchase.id
            mov.payment_condition = payment_condition
            mov.due_date = due_date_val

            items_payload.append({
                'code': prod.code,
                'name': prod.name,
                'quantity': it['quantity'],
                'unit_cost': it['unit_cost'],
                'total': it['line_total']
            })

        # 3. Financial Movement (Cash Outflow ONLY for amount actually paid!)
        fin_mov = None
        if paid_amount > 0:
            fin_mov = FinancialMovement(
                code=f"FIN-GAS-COM-{purchase.id:05d}",
                movement_type='Gasto',
                category='Compra' if not is_credit else 'Pago_Proveedor',
                amount=round(paid_amount, 2),
                payment_method=payment_method,
                description=(
                    f"Pago por Compra #{purchase_number} - {supplier.company_name} "
                    f"(Factura: {supplier_invoice or 'S/N'})"
                    + (" [Contado]" if not is_credit else f" [Abono Inicial C$ {paid_amount:,.2f}]")
                ),
                purchase_id=purchase.id,
                user_id=user_id,
                date=datetime.utcnow().date(),
                created_at=datetime.utcnow()
            )
            db.session.add(fin_mov)

        # 4. Inmutable Receipt
        receipt_payload = {
            'purchase_number': purchase_number,
            'supplier_name': supplier.company_name,
            'supplier_ruc': supplier.ruc,
            'supplier_invoice_number': supplier_invoice,
            'payment_method': payment_method,
            'payment_condition': payment_condition,
            'subtotal': round(subtotal, 2),
            'tax_amount': round(tax_amount, 2),
            'discount_amount': round(discount_amount, 2),
            'total': total_amount,
            'paid_amount': round(paid_amount, 2),
            'balance_due': purchase.balance_due,
            'payment_status': purchase.payment_status,
            'due_date': due_date_val.strftime('%Y-%m-%d') if due_date_val else None,
            'notes': notes,
            'date': purchase.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'items': items_payload
        }

        receipt = Receipt(
            receipt_number=f"REC-COM-{purchase_number}",
            receipt_type='Compra',
            related_purchase_id=purchase.id,
            supplier_id=supplier.id,
            user_id=user_id,
            client_name_snapshot=supplier.company_name,
            client_ruc_snapshot=supplier.ruc,
            subtotal=round(subtotal, 2),
            tax_amount=round(tax_amount, 2),
            discount_amount=round(discount_amount, 2),
            total_amount=total_amount,
            payment_method=payment_method,
            payment_condition=payment_condition,
            status='confirmado',
            notes=notes,
            payload_json=json.dumps(receipt_payload, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.session.add(receipt)
        db.session.flush()

        purchase.receipt_id = receipt.id
        if fin_mov:
            fin_mov.receipt_id = receipt.id

        # 5. Audit Log
        audit = AuditLog(
            user_id=user_id,
            action='CREATE_PURCHASE',
            entity_type='Purchase',
            entity_id=str(purchase.id),
            details=(
                f"Compra #{purchase_number} registrada a {supplier.company_name} por C$ {total_amount:,.2f} "
                f"({payment_condition}, Pagado inicial: C$ {paid_amount:,.2f}, Saldo por pagar: C$ {purchase.balance_due:,.2f})"
            )
        )
        db.session.add(audit)
        db.session.commit()

        try:
            TelegramService.notify_purchase(current_app._get_current_object(), purchase, receipt)
        except Exception:
            pass

        return purchase, receipt

    @staticmethod
    def void_purchase(purchase_id, user_id, reason):
        """
        Logically voids a purchase:
        - Validates sufficient stock exists to reverse the purchased items.
        - Deducts the quantity with compensatory movement 'Ajuste_Salida'.
        - Registers compensatory financial inflow ONLY for the money that was actually paid (purchase.paid_amount > 0).
        - Marks any associated PurchasePayments as 'anulado'.
        - Marks purchase and receipt as 'anulada'.
        - Full audit trail.
        """
        if not reason or len(reason.strip()) < 5:
            raise ValueError("Debe proporcionar un motivo válido de al menos 5 caracteres.")

        purchase = db.session.query(Purchase).filter_by(id=purchase_id).with_for_update().first()
        if not purchase:
            raise ValueError("Compra no encontrada.")
        if purchase.status == 'anulada':
            raise ValueError("La compra ya se encuentra anulada.")

        # Check stock sufficiency before deducting
        for item in purchase.items:
            prod = db.session.get(Product, item.product_id)
            if prod and prod.current_stock < item.quantity:
                raise ValueError(
                    f"No se puede anular la compra: el producto '{prod.name}' solo tiene "
                    f"{prod.current_stock:.2f} en existencia (se compraron {item.quantity:.2f})."
                )

        # Deduct purchased quantities
        for item in purchase.items:
            if item.product_id:
                InventoryService.record_movement(
                    product_id=item.product_id,
                    operation_type='Ajuste_Salida',
                    quantity=item.quantity,
                    user_id=user_id,
                    reason=f"Anulación Compra #{purchase.purchase_number}: {reason}",
                    notes="Deducción compensatoria por compra de mercancía anulada",
                    supplier_id=purchase.supplier_id,
                    unit_cost=item.unit_cost
                )

        # Reversal of funds ONLY if money was actually paid out
        if (purchase.paid_amount or 0.0) > 0:
            fin_mov = FinancialMovement(
                code=f"FIN-ING-ANU-COM-{purchase.id:05d}",
                movement_type='Ingreso',
                category='Devolucion_Proveedor',
                amount=round(purchase.paid_amount, 2),
                payment_method=purchase.payment_method,
                description=f"Recuperación compensatoria por anulación Compra #{purchase.purchase_number}. Motivo: {reason}",
                purchase_id=purchase.id,
                user_id=user_id,
                date=datetime.utcnow().date(),
                created_at=datetime.utcnow()
            )
            db.session.add(fin_mov)

        # Mark any associated supplier payments as voided
        for pp in purchase.payments:
            if pp.status != 'anulado':
                pp.status = 'anulado'
                pp.void_reason = f"Compra principal anulada: {reason}"
                pp.voided_by_id = user_id
                pp.voided_at = datetime.utcnow()

        purchase.status = 'anulada'
        purchase.void_reason = reason
        purchase.voided_by_id = user_id
        purchase.voided_at = datetime.utcnow()

        if purchase.receipt:
            purchase.receipt.status = 'anulado'
            purchase.receipt.void_reason = reason
            purchase.receipt.voided_by_id = user_id
            purchase.receipt.voided_at = datetime.utcnow()

        audit = AuditLog(
            user_id=user_id,
            action='VOID_PURCHASE',
            entity_type='Purchase',
            entity_id=str(purchase.id),
            details=f"Compra #{purchase.purchase_number} ANULADA. Motivo: {reason}"
        )
        db.session.add(audit)
        db.session.commit()
        return purchase
