from datetime import datetime
import json
from extensions import db
from models import Product, Client, Supplier, Sale, InventoryMovement, FinancialMovement, Receipt, AuditLog
from services.inventory_service import InventoryService

class ReturnsService:
    @staticmethod
    def process_client_return(product_id, quantity, unit_refund_price, client_id=None, sale_id=None, reason="", user_id=None):
        """
        Processes a customer return:
        - Re-stocks the product (Devolucion_Cliente).
        - Issues a cash refund financial movement if unit_refund_price > 0.
        - Emits an immutable Return Receipt.
        """
        product = db.session.query(Product).filter_by(id=product_id).with_for_update().first()
        if not product:
            raise ValueError("Producto no encontrado.")

        qty = float(quantity)
        if qty <= 0:
            raise ValueError("La cantidad a devolver debe ser mayor a 0.")

        unit_refund = float(unit_refund_price or product.sale_price)
        total_refund = round(qty * unit_refund, 2)

        client = Client.query.get(client_id) if client_id else None
        sale = Sale.query.get(sale_id) if sale_id else None

        # 1. Inventory movement (Inflow from client return)
        inv_mov = InventoryService.record_movement(
            product_id=product.id,
            operation_type='Devolucion_Cliente',
            quantity=qty,
            user_id=user_id,
            reason=f"Devolución de cliente: {reason}",
            notes=f"Cliente: {client.name if client else 'Mostrador'}" + (f", Factura #{sale.invoice_number}" if sale else ""),
            client_id=client.id if client else None,
            sale_id=sale.id if sale else None,
            invoice_number=sale.invoice_number if sale else None,
            unit_price=unit_refund,
            unit_cost=product.purchase_price
        )

        # 2. Financial Movement (Cash Outflow / Refund)
        fin_mov = None
        if total_refund > 0:
            fin_mov = FinancialMovement(
                code=f"FIN-GAS-DEV-CLI-{inv_mov.id:05d}",
                movement_type='Gasto',
                category='Devolucion_Cliente',
                amount=total_refund,
                payment_method='Efectivo',
                description=f"Reembolso por devolución de {qty:.2f} {product.unit} de {product.name}. Motivo: {reason}",
                sale_id=sale.id if sale else None,
                user_id=user_id,
                date=datetime.utcnow().date(),
                created_at=datetime.utcnow()
            )
            db.session.add(fin_mov)

        # 3. Immutable Receipt
        now_str = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        receipt_num = f"REC-DEV-CLI-{now_str[-6:]}"
        receipt_payload = {
            'receipt_number': receipt_num,
            'type': 'Devolución de Cliente',
            'product_code': product.code,
            'product_name': product.name,
            'quantity': qty,
            'unit_price': unit_refund,
            'total_refund': total_refund,
            'client_name': client.name if client else 'Cliente Ocasional',
            'reason': reason,
            'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        }

        receipt = Receipt(
            receipt_number=receipt_num,
            receipt_type='Devolucion',
            related_sale_id=sale.id if sale else None,
            client_id=client.id if client else None,
            user_id=user_id,
            client_name_snapshot=client.name if client else 'Cliente Ocasional',
            subtotal=total_refund,
            total_amount=total_refund,
            payment_method='Efectivo',
            status='confirmado',
            notes=reason,
            payload_json=json.dumps(receipt_payload, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.session.add(receipt)
        db.session.flush()

        if fin_mov:
            fin_mov.receipt_id = receipt.id

        # 4. Audit Log
        audit = AuditLog(
            user_id=user_id,
            action='CLIENT_RETURN',
            entity_type='Product',
            entity_id=str(product.id),
            details=f"Devolución de cliente registrada para {qty}x {product.name} (Total C$ {total_refund:,.2f})"
        )
        db.session.add(audit)
        db.session.commit()

        return inv_mov, receipt

    @staticmethod
    def process_supplier_return(product_id, quantity, supplier_id, unit_cost_reimbursement=None, reason="", user_id=None):
        """
        Processes a return of goods back to a supplier (damaged, expired, defective):
        - Deducts stock from inventory (Devolucion_Proveedor).
        - Records incoming refund / credit note (FinancialMovement).
        - Emits Return Receipt.
        """
        product = db.session.query(Product).filter_by(id=product_id).with_for_update().first()
        if not product:
            raise ValueError("Producto no encontrado.")

        qty = float(quantity)
        if qty <= 0:
            raise ValueError("La cantidad a devolver al proveedor debe ser mayor a 0.")
        if product.current_stock < qty:
            raise ValueError(f"Existencias insuficientes para devolver al proveedor. Disponible: {product.current_stock:.2f}")

        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            raise ValueError("Proveedor no encontrado.")

        reimbursement = float(unit_cost_reimbursement or product.purchase_price)
        total_reimbursement = round(qty * reimbursement, 2)

        # 1. Inventory movement (Stock Outflow)
        inv_mov = InventoryService.record_movement(
            product_id=product.id,
            operation_type='Devolucion_Proveedor',
            quantity=qty,
            user_id=user_id,
            reason=f"Devolución a proveedor: {reason}",
            notes=f"Proveedor: {supplier.company_name}",
            supplier_id=supplier.id,
            unit_cost=reimbursement
        )

        # 2. Financial Movement (Recovery / Inflow)
        fin_mov = None
        if total_reimbursement > 0:
            fin_mov = FinancialMovement(
                code=f"FIN-ING-DEV-PRV-{inv_mov.id:05d}",
                movement_type='Ingreso',
                category='Devolucion_Proveedor',
                amount=total_reimbursement,
                payment_method='Efectivo',
                description=f"Recuperación por devolución de {qty:.2f} {product.unit} de {product.name} a {supplier.company_name}. Motivo: {reason}",
                user_id=user_id,
                date=datetime.utcnow().date(),
                created_at=datetime.utcnow()
            )
            db.session.add(fin_mov)

        # 3. Immutable Receipt
        now_str = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        receipt_num = f"REC-DEV-PRV-{now_str[-6:]}"
        receipt_payload = {
            'receipt_number': receipt_num,
            'type': 'Devolución a Proveedor',
            'product_code': product.code,
            'product_name': product.name,
            'quantity': qty,
            'unit_cost': reimbursement,
            'total_reimbursement': total_reimbursement,
            'supplier_name': supplier.company_name,
            'supplier_ruc': supplier.ruc,
            'reason': reason,
            'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        }

        receipt = Receipt(
            receipt_number=receipt_num,
            receipt_type='Devolucion',
            supplier_id=supplier.id,
            user_id=user_id,
            client_name_snapshot=supplier.company_name,
            client_ruc_snapshot=supplier.ruc,
            subtotal=total_reimbursement,
            total_amount=total_reimbursement,
            payment_method='Efectivo',
            status='confirmado',
            notes=reason,
            payload_json=json.dumps(receipt_payload, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.session.add(receipt)
        db.session.flush()

        if fin_mov:
            fin_mov.receipt_id = receipt.id

        # 4. Audit Log
        audit = AuditLog(
            user_id=user_id,
            action='SUPPLIER_RETURN',
            entity_type='Product',
            entity_id=str(product.id),
            details=f"Devolución a proveedor {supplier.company_name} registrada para {qty}x {product.name} (Total C$ {total_reimbursement:,.2f})"
        )
        db.session.add(audit)
        db.session.commit()

        return inv_mov, receipt
