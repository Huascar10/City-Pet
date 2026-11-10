from datetime import datetime
from extensions import db
from models import Product, InventoryMovement, AuditLog, User
from services.inventory_service import InventoryService

class ReconciliationService:
    INFLOW_TYPES = {'Compra', 'Ajuste_Entrada', 'Devolucion_Cliente', 'Inventario_Inicial'}
    OUTFLOW_TYPES = {'Venta', 'Regalias', 'Ajuste_Salida', 'Danado_Merma', 'Devolucion_Proveedor'}

    @classmethod
    def get_product_reconciliation_data(cls, product_id=None):
        """
        Computes detailed mathematical 3-way reconciliation for products:
        1. Stock almacenado en productos (current_stock)
        2. Stock reconstruido desde el Kardex (theoretical_stock = initial + inflows - outflows)
        3. Stock físico declarado (physical_stock)
        Includes breakdown of historical movements vs operational movements and required action.
        """
        query = Product.query
        if product_id:
            query = query.filter_by(id=product_id)
        products = query.order_by(Product.code.asc()).all()

        results = []
        for p in products:
            movements = InventoryMovement.query.filter(
                InventoryMovement.product_id == p.id,
                InventoryMovement.status != 'anulado'
            ).all()

            initial_stock = 0.0
            hist_in = 0.0
            hist_out = 0.0
            op_in = 0.0
            op_out = 0.0
            total_in = 0.0
            total_out = 0.0

            for m in movements:
                op = m.operation_type
                is_hist = bool(m.code and m.code.startswith('MOV-HIST-'))
                if op == 'Inventario_Inicial':
                    initial_stock += m.quantity
                elif op in ('Compra', 'Ajuste_Entrada', 'Devolucion_Cliente'):
                    total_in += m.quantity
                    if is_hist:
                        hist_in += m.quantity
                    else:
                        op_in += m.quantity
                elif op in ('Venta', 'Regalias', 'Ajuste_Salida', 'Danado_Merma', 'Devolucion_Proveedor'):
                    total_out += m.quantity
                    if is_hist:
                        hist_out += m.quantity
                    else:
                        op_out += m.quantity

            theoretical_stock = round(initial_stock + total_in - total_out, 2)
            db_stock = round(p.current_stock, 2)
            physical_stock = round(p.physical_stock, 2)

            history_diff = round(db_stock - theoretical_stock, 2)
            physical_diff = round(physical_stock - db_stock, 2)

            has_discrepancy = abs(history_diff) > 0.001 or abs(physical_diff) > 0.001

            if abs(physical_diff) <= 0.001 and abs(history_diff) <= 0.001:
                required_action = "Conciliado — Sin acción requerida"
            elif physical_diff < -0.001:
                required_action = f"Validar conteo en bodega y aplicar Ajuste de Salida ({physical_diff:+.0f} {p.unit})"
            elif physical_diff > 0.001:
                required_action = f"Validar conteo en bodega y aplicar Ajuste de Entrada ({physical_diff:+.0f} {p.unit})"
            else:
                required_action = f"Diferencia histórica Kardex ({history_diff:+.0f} {p.unit}) — Stock físico coincide con sistema"

            results.append({
                'product_id': p.id,
                'code': p.code,
                'name': p.name,
                'category': p.category,
                'unit': p.unit,
                'initial_stock': round(initial_stock, 2),
                'hist_in': round(hist_in, 2),
                'hist_out': round(hist_out, 2),
                'op_in': round(op_in, 2),
                'op_out': round(op_out, 2),
                'total_in': round(total_in, 2),
                'total_out': round(total_out, 2),
                'theoretical_stock': theoretical_stock,
                'current_stock': db_stock,
                'physical_stock': physical_stock,
                'history_diff': history_diff,
                'physical_diff': physical_diff,
                'has_discrepancy': has_discrepancy,
                'required_action': required_action,
                'purchase_price': p.purchase_price,
                'value_diff': round(physical_diff * p.purchase_price, 2)
            })

        return results

    @classmethod
    def apply_adjustment(cls, product_id, target_stock, reason, user_id=None):
        """
        Applies a formal, auditable physical inventory adjustment:
        Records:
        - Stock anterior (previous_stock)
        - Conteo físico (target_stock)
        - Diferencia (diff)
        - Stock final (new_stock)
        - Motivo (reason)
        - Usuario responsable (user_id)
        - Fecha y hora (created_at)
        """
        if not reason or len(str(reason).strip()) < 5:
            raise ValueError("Debe ingresar un motivo de justificación obligatorio de al menos 5 caracteres.")

        product = db.session.query(Product).filter_by(id=int(product_id)).with_for_update().first() if product_id else None
        if not product:
            raise ValueError("Producto no encontrado.")

        target = round(float(target_stock), 2)
        if target < 0:
            raise ValueError("El conteo físico no puede ser negativo.")

        previous_stock = round(float(product.current_stock or 0.0), 2)
        diff = round(target - previous_stock, 2)
        user_obj = db.session.get(User, int(user_id)) if user_id else None
        user_label = user_obj.username if user_obj else 'Sistema'

        if abs(diff) < 0.001:
            product.physical_stock = target
            audit = AuditLog(
                user_id=user_id,
                user_name=user_label,
                action='INVENTORY_PHYSICAL_VERIFY',
                entity_type='Product',
                entity_id=str(product.id),
                details=(
                    f"Verificación física sin diferencia para '{product.name}' ({product.code}). "
                    f"Stock anterior: {previous_stock:.2f}, Conteo físico: {target:.2f}, Diferencia: 0.00, "
                    f"Stock final: {target:.2f}. Motivo: {reason}"
                )
            )
            db.session.add(audit)
            db.session.commit()
            return None

        op_type = 'Ajuste_Entrada' if diff > 0 else 'Ajuste_Salida'
        structured_notes = (
            f"Stock anterior: {previous_stock:.2f} | Conteo físico: {target:.2f} | "
            f"Diferencia: {diff:+.2f} | Stock final: {target:.2f} | Responsable: {user_label}"
        )

        mov = InventoryService.record_movement(
            product_id=product.id,
            operation_type=op_type,
            quantity=abs(diff),
            user_id=user_id,
            reason=f"Ajuste físico formal: {reason}",
            notes=structured_notes,
            unit_price=product.sale_price,
            unit_cost=product.purchase_price
        )

        product.physical_stock = target
        audit = AuditLog(
            user_id=user_id,
            user_name=user_label,
            action='INVENTORY_RECONCILIATION_ADJUST',
            entity_type='Product',
            entity_id=str(product.id),
            details=(
                f"Ajuste físico formal para '{product.name}' ({product.code}). "
                f"Stock anterior: {previous_stock:.2f} {product.unit}, "
                f"Conteo físico: {target:.2f} {product.unit}, "
                f"Diferencia: {diff:+.2f} {product.unit}, "
                f"Stock final: {target:.2f} {product.unit}. "
                f"Movimiento: {mov.code}. Motivo: {reason}"
            )
        )
        db.session.add(audit)
        db.session.commit()

        return mov
