from datetime import datetime, timedelta
import json
from flask import current_app
from extensions import db
from models import Sale, Payment, Purchase, PurchasePayment, FinancialMovement, Receipt, AuditLog
from services.telegram_service import TelegramService

class PaymentService:
    @staticmethod
    def get_next_payment_number():
        """Generates consecutive client payment number e.g. ABN-202611-0001"""
        now = datetime.utcnow()
        prefix = f"ABN-{now.strftime('%Y%m')}-"
        last = Payment.query.filter(Payment.payment_number.like(f"{prefix}%")).order_by(Payment.id.desc()).first()
        if not last:
            return f"{prefix}0001"
        try:
            seq = int(last.payment_number.split('-')[-1]) + 1
            return f"{prefix}{seq:04d}"
        except Exception:
            return f"{prefix}{last.id + 1:04d}"

    @staticmethod
    def get_next_supplier_payment_number():
        """Generates consecutive supplier payment number e.g. PAG-202611-0001"""
        now = datetime.utcnow()
        prefix = f"PAG-{now.strftime('%Y%m')}-"
        last = PurchasePayment.query.filter(PurchasePayment.payment_number.like(f"{prefix}%")).order_by(PurchasePayment.id.desc()).first()
        if not last:
            return f"{prefix}0001"
        try:
            seq = int(last.payment_number.split('-')[-1]) + 1
            return f"{prefix}{seq:04d}"
        except Exception:
            return f"{prefix}{last.id + 1:04d}"

    @staticmethod
    def generate_preview(sale_id, amount, payment_method='Efectivo'):
        """Generates simulated calculation for a client abono with watermark."""
        sale = db.session.get(Sale, int(sale_id)) if sale_id else None
        if not sale:
            raise ValueError("Venta no encontrada.")
        if sale.status == 'anulada':
            raise ValueError("La factura está anulada; no se pueden registrar abonos.")

        amount = float(amount)
        if amount <= 0:
            raise ValueError("El monto del abono debe ser mayor a 0.")
        if amount > sale.balance_due + 0.01:
            raise ValueError(f"El monto (C$ {amount:,.2f}) excede el saldo pendiente (C$ {sale.balance_due:,.2f}).")

        prev_balance = sale.balance_due
        new_bal = max(0.0, round(prev_balance - amount, 2))

        return {
            'is_preview': True,
            'watermark': 'VISTA PREVIA — RECIBO DE ABONO NO CONFIRMADO',
            'simulated_payment_number': PaymentService.get_next_payment_number(),
            'invoice_number': sale.invoice_number,
            'client_name': sale.client_name,
            'client_ruc': sale.client_ruc,
            'invoice_total': sale.total,
            'previous_balance': prev_balance,
            'amount': amount,
            'new_balance': new_bal,
            'payment_method': payment_method
        }

    @staticmethod
    def register_abono(sale_id, amount, payment_method='Efectivo', reference=None, notes=None, user_id=None, idempotency_token=None):
        """
        Registers an atomic debt payment towards a credit sale:
        1. Checks idempotency token and duplicate submission.
        2. Locks Sale row and validates amount against outstanding balance.
        3. Records Payment entity.
        4. Increments sale.paid_amount (auto-transitions to Liquidado when balance_due == 0).
        5. Records FinancialMovement (Ingreso).
        6. Emits immutable Receipt of Abono.
        7. Audit log.
        """
        if idempotency_token:
            existing = Payment.query.filter_by(idempotency_token=idempotency_token).first()
            if existing:
                raise ValueError(f"Operación duplicada detectada: El abono #{existing.payment_number} ya fue procesado.")

        sale = db.session.query(Sale).filter_by(id=int(sale_id)).with_for_update().first() if sale_id else None
        if not sale:
            raise ValueError("Factura no encontrada.")
        if sale.status == 'anulada':
            raise ValueError("No se puede registrar abonos a una factura anulada.")
        if sale.balance_due <= 0.001:
            raise ValueError(f"La factura #{sale.invoice_number} ya se encuentra completamente liquidada (Saldo: C$ 0.00).")

        amount = round(float(amount or 0.0), 2)
        if amount <= 0:
            raise ValueError("El monto del abono debe ser mayor a 0.")
        if amount > sale.balance_due + 0.01:
            raise ValueError(f"El monto (C$ {amount:,.2f}) excede el saldo pendiente de la factura (C$ {sale.balance_due:,.2f}).")

        # Clamp if within 1 cent rounding
        if amount > sale.balance_due:
            amount = sale.balance_due

        payment_number = PaymentService.get_next_payment_number()
        previous_balance = sale.balance_due
        new_balance = max(0.0, round(previous_balance - amount, 2))

        # 1. Payment record
        payment = Payment(
            payment_number=payment_number,
            sale_id=sale.id,
            client_id=sale.client_id,
            user_id=user_id,
            amount=amount,
            previous_balance=round(previous_balance, 2),
            new_balance=new_balance,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            status='confirmado',
            idempotency_token=idempotency_token,
            created_at=datetime.utcnow()
        )
        db.session.add(payment)

        # 2. Update sale paid amount
        sale.paid_amount = round((sale.paid_amount or 0.0) + amount, 2)
        db.session.flush()

        # 3. Financial Movement (Ingreso por Abono de Venta)
        fin_mov = FinancialMovement(
            code=f"FIN-ING-ABN-{payment.id:05d}",
            movement_type='Ingreso',
            category='Abono_Venta',
            amount=amount,
            payment_method=payment_method,
            description=f"Abono Factura #{sale.invoice_number} - {sale.client_name} (Saldo Restante: C$ {new_balance:,.2f})",
            sale_id=sale.id,
            payment_id=payment.id,
            user_id=user_id,
            date=datetime.utcnow().date(),
            created_at=datetime.utcnow()
        )
        db.session.add(fin_mov)

        # 4. Inmutable Receipt of Abono
        receipt_payload = {
            'payment_number': payment_number,
            'invoice_number': sale.invoice_number,
            'client_name': sale.client_name,
            'client_ruc': sale.client_ruc,
            'client_code': sale.client_code,
            'salesperson': sale.salesperson,
            'total_invoice': sale.total,
            'previous_balance': round(previous_balance, 2),
            'amount_paid': amount,
            'new_balance': new_balance,
            'invoice_status': sale.payment_status,
            'payment_method': payment_method,
            'reference': reference or 'N/A',
            'notes': notes or '',
            'date': payment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

        receipt = Receipt(
            receipt_number=f"REC-ABN-{payment_number}",
            receipt_type='Abono',
            related_sale_id=sale.id,
            related_payment_id=payment.id,
            client_id=sale.client_id,
            user_id=user_id,
            client_name_snapshot=sale.client_name,
            client_ruc_snapshot=sale.client_ruc,
            client_code_snapshot=sale.client_code,
            salesperson_snapshot=sale.salesperson,
            subtotal=amount,
            total_amount=amount,
            payment_method=payment_method,
            payment_condition='Abono a Cuenta',
            status='confirmado',
            notes=notes,
            payload_json=json.dumps(receipt_payload, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.session.add(receipt)
        db.session.flush()

        payment.receipt_id = receipt.id
        fin_mov.receipt_id = receipt.id

        # 5. Audit Log
        audit = AuditLog(
            user_id=user_id,
            action='REGISTER_ABONO',
            entity_type='Payment',
            entity_id=str(payment.id),
            details=f"Abono #{payment_number} por C$ {amount:,.2f} a Factura #{sale.invoice_number} de {sale.client_name} (Nuevo saldo: C$ {new_balance:,.2f}, Estado: {sale.payment_status})"
        )
        db.session.add(audit)
        db.session.commit()

        try:
            TelegramService.notify_payment(current_app._get_current_object(), payment, sale)
        except Exception:
            pass

        return payment, receipt

    @staticmethod
    def void_abono(payment_id, user_id, reason):
        """
        Logically voids a client abono:
        - Reverts sale.paid_amount.
        - Records compensatory financial outflow.
        - Marks payment and receipt as 'anulado'.
        - Full audit trail.
        """
        if not reason or len(reason.strip()) < 5:
            raise ValueError("Debe proporcionar un motivo válido de al menos 5 caracteres.")

        payment = db.session.query(Payment).filter_by(id=int(payment_id)).with_for_update().first()
        if not payment:
            raise ValueError("Abono no encontrado.")
        if payment.status == 'anulado':
            raise ValueError("El abono ya se encuentra anulado.")

        sale = payment.sale
        sale.paid_amount = max(0.0, round((sale.paid_amount or 0.0) - payment.amount, 2))

        fin_mov = FinancialMovement(
            code=f"FIN-GAS-ANU-ABN-{payment.id:05d}",
            movement_type='Gasto',
            category='Devolucion',
            amount=payment.amount,
            payment_method=payment.payment_method,
            description=f"Salida compensatoria por anulación Abono #{payment.payment_number} Factura #{sale.invoice_number}. Motivo: {reason}",
            sale_id=sale.id,
            payment_id=payment.id,
            user_id=user_id,
            date=datetime.utcnow().date(),
            created_at=datetime.utcnow()
        )
        db.session.add(fin_mov)

        payment.status = 'anulado'
        payment.void_reason = reason
        payment.voided_by_id = user_id
        payment.voided_at = datetime.utcnow()

        if payment.receipt:
            payment.receipt.status = 'anulado'
            payment.receipt.void_reason = reason
            payment.receipt.voided_by_id = user_id
            payment.receipt.voided_at = datetime.utcnow()

        audit = AuditLog(
            user_id=user_id,
            action='VOID_ABONO',
            entity_type='Payment',
            entity_id=str(payment.id),
            details=f"Abono #{payment.payment_number} ANULADO. Motivo: {reason}"
        )
        db.session.add(audit)
        db.session.commit()
        return payment

    @staticmethod
    def register_supplier_payment(purchase_id, amount, payment_method='Efectivo', reference=None, notes=None, user_id=None, idempotency_token=None):
        """
        Registers an atomic payment towards a supplier credit purchase (Accounts Payable):
        1. Checks idempotency token and prevents duplicate payment.
        2. Locks Purchase row and validates amount against balance_due.
        3. Creates PurchasePayment entity.
        4. Increments purchase.paid_amount (auto-transitions to Liquidado when balance_due == 0).
        5. Records real cash outflow FinancialMovement (Gasto / Pago_Proveedor).
        6. Emits immutable Receipt of Pago_Proveedor.
        7. Audit log.
        """
        if idempotency_token:
            existing = PurchasePayment.query.filter_by(idempotency_token=idempotency_token).first()
            if existing:
                raise ValueError(f"Operación duplicada detectada: El pago a proveedor #{existing.payment_number} ya fue registrado.")

        purchase = db.session.query(Purchase).filter_by(id=int(purchase_id)).with_for_update().first() if purchase_id else None
        if not purchase:
            raise ValueError("Compra no encontrada.")
        if purchase.status == 'anulada':
            raise ValueError("No se puede registrar pagos a una compra anulada.")
        if purchase.balance_due <= 0.001:
            raise ValueError(f"La compra #{purchase.purchase_number} ya se encuentra completamente liquidada (Saldo: C$ 0.00).")

        amount = round(float(amount or 0.0), 2)
        if amount <= 0:
            raise ValueError("El importe del pago al proveedor debe ser mayor a 0.")
        if amount > purchase.balance_due + 0.01:
            raise ValueError(
                f"El importe del pago (C$ {amount:,.2f}) supera el saldo pendiente de la factura del proveedor (C$ {purchase.balance_due:,.2f})."
            )

        if amount > purchase.balance_due:
            amount = purchase.balance_due

        payment_number = PaymentService.get_next_supplier_payment_number()
        previous_balance = purchase.balance_due
        new_balance = max(0.0, round(previous_balance - amount, 2))

        # 1. PurchasePayment record
        supp_payment = PurchasePayment(
            payment_number=payment_number,
            purchase_id=purchase.id,
            supplier_id=purchase.supplier_id,
            user_id=user_id,
            amount=amount,
            previous_balance=round(previous_balance, 2),
            new_balance=new_balance,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            status='confirmado',
            idempotency_token=idempotency_token,
            created_at=datetime.utcnow()
        )
        db.session.add(supp_payment)

        # 2. Update purchase paid amount
        purchase.paid_amount = round((purchase.paid_amount or 0.0) + amount, 2)
        db.session.flush()

        # 3. Real cash outflow in FinancialMovement
        fin_mov = FinancialMovement(
            code=f"FIN-GAS-PAG-{supp_payment.id:05d}",
            movement_type='Gasto',
            category='Pago_Proveedor',
            amount=amount,
            payment_method=payment_method,
            description=(
                f"Pago a Proveedor #{payment_number} — Compra #{purchase.purchase_number} "
                f"({purchase.supplier_name_snapshot}). Saldo restante: C$ {new_balance:,.2f}"
            ),
            purchase_id=purchase.id,
            purchase_payment_id=supp_payment.id,
            user_id=user_id,
            date=datetime.utcnow().date(),
            created_at=datetime.utcnow()
        )
        db.session.add(fin_mov)

        # 4. Immutable Receipt
        receipt_payload = {
            'payment_number': payment_number,
            'purchase_number': purchase.purchase_number,
            'supplier_invoice_number': purchase.supplier_invoice_number or 'S/N',
            'supplier_name': purchase.supplier_name_snapshot,
            'supplier_ruc': purchase.supplier_ruc_snapshot,
            'total_purchase': purchase.total,
            'previous_balance': round(previous_balance, 2),
            'amount_paid': amount,
            'new_balance': new_balance,
            'purchase_status': purchase.payment_status,
            'payment_method': payment_method,
            'reference': reference or 'N/A',
            'notes': notes or '',
            'date': supp_payment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

        receipt = Receipt(
            receipt_number=f"REC-PAG-{payment_number}",
            receipt_type='Pago_Proveedor',
            related_purchase_id=purchase.id,
            related_purchase_payment_id=supp_payment.id,
            supplier_id=purchase.supplier_id,
            user_id=user_id,
            client_name_snapshot=purchase.supplier_name_snapshot,
            client_ruc_snapshot=purchase.supplier_ruc_snapshot,
            subtotal=amount,
            total_amount=amount,
            payment_method=payment_method,
            payment_condition='Pago a Proveedor',
            status='confirmado',
            notes=notes,
            payload_json=json.dumps(receipt_payload, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.session.add(receipt)
        db.session.flush()

        supp_payment.receipt_id = receipt.id
        fin_mov.receipt_id = receipt.id

        # 5. Audit Log
        audit = AuditLog(
            user_id=user_id,
            action='REGISTER_SUPPLIER_PAYMENT',
            entity_type='PurchasePayment',
            entity_id=str(supp_payment.id),
            details=(
                f"Pago a proveedor #{payment_number} por C$ {amount:,.2f} aplicado a Compra #{purchase.purchase_number} "
                f"({purchase.supplier_name_snapshot}). Nuevo saldo: C$ {new_balance:,.2f} ({purchase.payment_status})"
            )
        )
        db.session.add(audit)
        db.session.commit()

        try:
            TelegramService.notify_supplier_payment(current_app._get_current_object(), supp_payment, purchase)
        except Exception:
            pass

        return supp_payment, receipt

    @staticmethod
    def void_supplier_payment(payment_id, user_id, reason):
        """
        Logically voids a supplier payment:
        - Reverts purchase.paid_amount.
        - Records compensatory financial inflow.
        - Marks payment and receipt as 'anulado'.
        """
        if not reason or len(reason.strip()) < 5:
            raise ValueError("Debe proporcionar un motivo válido de al menos 5 caracteres.")

        supp_payment = db.session.query(PurchasePayment).filter_by(id=int(payment_id)).with_for_update().first()
        if not supp_payment:
            raise ValueError("Pago a proveedor no encontrado.")
        if supp_payment.status == 'anulado':
            raise ValueError("El pago ya se encuentra anulado.")

        purchase = supp_payment.purchase
        purchase.paid_amount = max(0.0, round((purchase.paid_amount or 0.0) - supp_payment.amount, 2))

        fin_mov = FinancialMovement(
            code=f"FIN-ING-ANU-PAG-{supp_payment.id:05d}",
            movement_type='Ingreso',
            category='Ajuste_Caja',
            amount=supp_payment.amount,
            payment_method=supp_payment.payment_method,
            description=f"Reintegro compensatorio por anulación Pago #{supp_payment.payment_number} Compra #{purchase.purchase_number}. Motivo: {reason}",
            purchase_id=purchase.id,
            purchase_payment_id=supp_payment.id,
            user_id=user_id,
            date=datetime.utcnow().date(),
            created_at=datetime.utcnow()
        )
        db.session.add(fin_mov)

        supp_payment.status = 'anulado'
        supp_payment.void_reason = reason
        supp_payment.voided_by_id = user_id
        supp_payment.voided_at = datetime.utcnow()

        if supp_payment.receipt:
            supp_payment.receipt.status = 'anulado'
            supp_payment.receipt.void_reason = reason
            supp_payment.receipt.voided_by_id = user_id
            supp_payment.receipt.voided_at = datetime.utcnow()

        audit = AuditLog(
            user_id=user_id,
            action='VOID_SUPPLIER_PAYMENT',
            entity_type='PurchasePayment',
            entity_id=str(supp_payment.id),
            details=f"Pago a proveedor #{supp_payment.payment_number} ANULADO. Motivo: {reason}"
        )
        db.session.add(audit)
        db.session.commit()
        return supp_payment
