from datetime import datetime
from extensions import db
from models import Product, InventoryMovement, AuditLog

class InventoryService:
    @staticmethod
    def generate_movement_code():
        year = datetime.utcnow().year
        last_mov = InventoryMovement.query.filter(
            InventoryMovement.code.like(f'MOV-{year}-%')
        ).order_by(InventoryMovement.id.desc()).first()
        
        if last_mov and last_mov.code:
            try:
                last_num = int(last_mov.code.split('-')[-1])
                new_num = last_num + 1
            except ValueError:
                new_num = 1
        else:
            new_num = 1
            
        return f'MOV-{year}-{new_num:05d}'

    @staticmethod
    def record_movement(
        product_id,
        operation_type,
        quantity,
        user_id=None,
        reason=None,
        notes=None,
        client_id=None,
        supplier_id=None,
        sale_id=None,
        receipt_id=None,
        invoice_number=None,
        salesperson=None,
        warehouse='Principal',
        unit_price=0.0,
        unit_cost=0.0
    ):
        """
        Records an inventory movement within the current DB session with strict non-negative check.
        Operation types:
          Inbound: 'Compra', 'Regalias', 'Devolucion_Cliente', 'Ajuste_Entrada', 'Inventario_Inicial'
          Outbound: 'Venta', 'Devolucion_Proveedor', 'Ajuste_Salida', 'Danado_Merma'
        """
        # Lock product row for update to prevent race conditions
        product = db.session.query(Product).filter_by(id=product_id).with_for_update().first()
        if not product:
            raise ValueError(f"Producto con ID {product_id} no encontrado.")

        qty = abs(float(quantity))
        previous_stock = float(product.current_stock or 0.0)

        inbound_types = {'Compra', 'Regalias', 'Devolucion_Cliente', 'Ajuste_Entrada', 'Inventario_Inicial'}
        outbound_types = {'Venta', 'Devolucion_Proveedor', 'Ajuste_Salida', 'Danado_Merma'}

        if operation_type in inbound_types:
            new_stock = previous_stock + qty
        elif operation_type in outbound_types:
            if previous_stock < qty:
                raise ValueError(
                    f"Existencias insuficientes para '{product.name}'. "
                    f"Disponibles: {previous_stock:.2f}, Solicitadas: {qty:.2f}."
                )
            new_stock = previous_stock - qty
        else:
            raise ValueError(f"Tipo de operación desconocido: '{operation_type}'.")

        # Update product stock
        product.current_stock = round(new_stock, 2)
        if unit_cost > 0:
            product.purchase_price = round(float(unit_cost), 2)
        if unit_price > 0:
            product.sale_price = round(float(unit_price), 2)
        product.updated_at = datetime.utcnow()

        # Compute total value
        val = round(qty * (unit_price if unit_price > 0 else (unit_cost if unit_cost > 0 else product.purchase_price)), 2)

        movement = InventoryMovement(
            code=InventoryService.generate_movement_code(),
            product_id=product.id,
            operation_type=operation_type,
            quantity=qty,
            previous_stock=previous_stock,
            new_stock=round(new_stock, 2),
            unit_price=unit_price,
            unit_cost=unit_cost,
            total_value=val,
            client_id=client_id,
            supplier_id=supplier_id,
            sale_id=sale_id,
            receipt_id=receipt_id,
            invoice_number=invoice_number,
            salesperson=salesperson,
            warehouse=warehouse or product.warehouse or 'Principal',
            reason=reason,
            notes=notes,
            user_id=user_id,
            created_at=datetime.utcnow()
        )
        db.session.add(movement)
        db.session.flush()
        return movement

    @staticmethod
    def reverse_movement(movement_id, user_id, reason):
        """
        Auditable reversal of a previous movement (no silent history modification).
        """
        orig = InventoryMovement.query.get(movement_id)
        if not orig:
            raise ValueError("Movimiento original no encontrado.")
        if orig.is_reversal:
            raise ValueError("No se puede revertir un movimiento que ya es una reversión.")

        product = db.session.query(Product).filter_by(id=orig.product_id).with_for_update().first()
        previous_stock = float(product.current_stock)

        inbound_types = {'Compra', 'Regalias', 'Devolucion_Cliente', 'Ajuste_Entrada', 'Inventario_Inicial'}
        
        # If original was inbound, reversing it means removing stock
        if orig.operation_type in inbound_types:
            if previous_stock < orig.quantity:
                raise ValueError(
                    f"No se puede revertir el movimiento: dejaría el stock en negativo ({previous_stock - orig.quantity})."
                )
            new_stock = previous_stock - orig.quantity
            rev_type = 'Ajuste_Salida'
        else:
            new_stock = previous_stock + orig.quantity
            rev_type = 'Ajuste_Entrada'

        product.current_stock = round(new_stock, 2)
        product.updated_at = datetime.utcnow()

        reversal = InventoryMovement(
            code=InventoryService.generate_movement_code(),
            product_id=product.id,
            operation_type=rev_type,
            quantity=orig.quantity,
            previous_stock=previous_stock,
            new_stock=round(new_stock, 2),
            unit_price=orig.unit_price,
            unit_cost=orig.unit_cost,
            total_value=orig.total_value,
            client_id=orig.client_id,
            supplier_id=orig.supplier_id,
            invoice_number=orig.invoice_number,
            salesperson=orig.salesperson,
            warehouse=orig.warehouse,
            reason=f"REVERSIÓN de {orig.code}: {reason}",
            notes=f"Reversión auditada del movimiento {orig.code}",
            user_id=user_id,
            is_reversal=True,
            reversal_of_id=orig.id,
            created_at=datetime.utcnow()
        )
        db.session.add(reversal)

        audit = AuditLog(
            user_id=user_id,
            action='REVERSAL_MOVEMENT',
            entity_type='InventoryMovement',
            entity_id=str(orig.id),
            details=f"Revertido movimiento {orig.code} ({orig.operation_type} {orig.quantity} unids de {product.name}). Motivo: {reason}"
        )
        db.session.add(audit)
        return reversal
