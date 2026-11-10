from datetime import datetime, date
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Product, InventoryMovement, Supplier, Client, AuditLog
from services.inventory_service import InventoryService
from services.reconciliation_service import ReconciliationService
from services.returns_service import ReturnsService
from routes.auth import admin_required

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')

@inventory_bp.route('/')
@login_required
def index():
    op_type = request.args.get('operation_type', '').strip()
    product_id = request.args.get('product_id', type=int)
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    query = InventoryMovement.query

    if op_type:
        query = query.filter_by(operation_type=op_type)
    if product_id:
        query = query.filter_by(product_id=product_id)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(InventoryMovement.created_at >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d')
            ed = datetime.combine(ed.date(), datetime.max.time())
            query = query.filter(InventoryMovement.created_at <= ed)
        except ValueError:
            pass

    movements = query.order_by(InventoryMovement.created_at.desc()).limit(200).all()

    products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name.asc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()

    operation_types = [
        'Compra', 'Venta', 'Regalias', 'Devolucion_Cliente',
        'Devolucion_Proveedor', 'Ajuste_Entrada', 'Ajuste_Salida', 'Danado_Merma', 'Inventario_Inicial'
    ]

    return render_template(
        'inventory/index.html',
        movements=movements,
        products=products,
        suppliers=suppliers,
        clients=clients,
        operation_types=operation_types,
        selected_op=op_type,
        selected_product=product_id,
        start_date=start_date,
        end_date=end_date
    )

@inventory_bp.route('/reconciliation', methods=['GET', 'POST'])
@login_required
@admin_required
def reconciliation():
    """
    Mathematical inventory reconciliation comparing:
    Theoretical Stock (Initial + Inflows - Outflows) vs System Stock vs Physical Count.
    """
    if request.method == 'POST':
        product_id = request.form.get('product_id', type=int)
        target_stock = request.form.get('target_stock')
        reason = request.form.get('reason', '').strip()

        try:
            mov = ReconciliationService.apply_adjustment(
                product_id=product_id,
                target_stock=target_stock,
                reason=reason,
                user_id=current_user.id
            )
            if request.is_json:
                return jsonify({'success': True, 'movement_code': mov.code if mov else None})
            flash(f"Ajuste de conciliación aplicado exitosamente. El inventario ha sido cuadrado.", "success")
        except ValueError as e:
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 400
            flash(str(e), "danger")
        except Exception as e:
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 500
            flash(f"Error al conciliar inventario: {str(e)}", "danger")

        return redirect(url_for('inventory.reconciliation'))

    reconciliation_data = ReconciliationService.get_product_reconciliation_data()
    discrepancies_count = sum(1 for item in reconciliation_data if item['has_discrepancy'])

    return render_template(
        'inventory/reconciliation.html',
        items=reconciliation_data,
        discrepancies_count=discrepancies_count,
        total_items=len(reconciliation_data)
    )

@inventory_bp.route('/movement/create', methods=['POST'])
@login_required
@admin_required
def create_movement():
    product_id = request.form.get('product_id', type=int)
    op_type = request.form.get('operation_type', '').strip()
    try:
        qty = abs(float(request.form.get('quantity') or 0.0))
    except ValueError:
        qty = 0.0

    if not product_id or not op_type or qty <= 0:
        flash("Datos inválidos para registrar movimiento. Verifique producto, tipo y cantidad.", "danger")
        return redirect(url_for('inventory.index'))

    supplier_id = request.form.get('supplier_id', type=int)
    client_id = request.form.get('client_id', type=int)
    invoice_number = request.form.get('invoice_number', '').strip() or None
    reason = request.form.get('reason', '').strip() or None
    notes = request.form.get('notes', '').strip() or None

    try: unit_cost = max(0.0, float(request.form.get('unit_cost') or 0.0))
    except ValueError: unit_cost = 0.0

    try: unit_price = max(0.0, float(request.form.get('unit_price') or 0.0))
    except ValueError: unit_price = 0.0

    try:
        mov = InventoryService.record_movement(
            product_id=product_id,
            operation_type=op_type,
            quantity=qty,
            user_id=current_user.id,
            reason=reason,
            notes=notes,
            client_id=client_id,
            supplier_id=supplier_id,
            invoice_number=invoice_number,
            unit_cost=unit_cost,
            unit_price=unit_price
        )
        db.session.commit()
        flash(f"Movimiento {mov.code} registrado con éxito. Stock actualizado.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al registrar movimiento: {str(e)}", "danger")

    return redirect(url_for('inventory.index'))

@inventory_bp.route('/movement/<int:id>/reverse', methods=['POST'])
@login_required
@admin_required
def reverse_movement(id):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Debe proporcionar un motivo para la reversión.", "warning")
        return redirect(url_for('inventory.index'))

    try:
        rev = InventoryService.reverse_movement(id, current_user.id, reason)
        db.session.commit()
        flash(f"Movimiento revertido exitosamente mediante el ajuste {rev.code}.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error inesperado al revertir: {str(e)}", "danger")

    return redirect(url_for('inventory.index'))

@inventory_bp.route('/returns/client', methods=['POST'])
@login_required
@admin_required
def client_return():
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity')
    unit_price = request.form.get('unit_price')
    client_id = request.form.get('client_id', type=int)
    reason = request.form.get('reason', '').strip()

    try:
        mov, receipt = ReturnsService.process_client_return(
            product_id=product_id,
            quantity=quantity,
            unit_refund_price=unit_price,
            client_id=client_id,
            reason=reason,
            user_id=current_user.id
        )
        flash(f"Devolución de cliente procesada exitosamente. Recibo #{receipt.receipt_number} generado.", "success")
        return redirect(url_for('receipts.view_receipt', id=receipt.id))
    except ValueError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Error al procesar devolución de cliente: {str(e)}", "danger")

    return redirect(url_for('inventory.index'))

@inventory_bp.route('/returns/supplier', methods=['POST'])
@login_required
@admin_required
def supplier_return():
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity')
    supplier_id = request.form.get('supplier_id', type=int)
    unit_cost = request.form.get('unit_cost')
    reason = request.form.get('reason', '').strip()

    try:
        mov, receipt = ReturnsService.process_supplier_return(
            product_id=product_id,
            quantity=quantity,
            supplier_id=supplier_id,
            unit_cost_reimbursement=unit_cost,
            reason=reason,
            user_id=current_user.id
        )
        flash(f"Devolución a proveedor procesada exitosamente. Recibo #{receipt.receipt_number} generado.", "success")
        return redirect(url_for('receipts.view_receipt', id=receipt.id))
    except ValueError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Error al procesar devolución a proveedor: {str(e)}", "danger")

    return redirect(url_for('inventory.index'))

@inventory_bp.route('/audit', methods=['GET', 'POST'])
@login_required
@admin_required
def audit():
    """Physical count audit matching Excel's FISICO vs EXISTENCIA ACTUAL."""
    if request.method == 'POST':
        product_id = request.form.get('product_id', type=int)
        product = Product.query.get_or_404(product_id)
        try:
            new_physical = max(0.0, float(request.form.get('physical_stock') or 0.0))
            product.physical_stock = new_physical
            
            auto_adjust = bool(request.form.get('auto_adjust'))
            if auto_adjust:
                diff = new_physical - product.current_stock
                if diff > 0:
                    InventoryService.record_movement(
                        product_id=product.id,
                        operation_type='Ajuste_Entrada',
                        quantity=diff,
                        user_id=current_user.id,
                        reason=f"Ajuste automático por conteo físico (+{diff:.2f})"
                    )
                elif diff < 0:
                    InventoryService.record_movement(
                        product_id=product.id,
                        operation_type='Ajuste_Salida',
                        quantity=abs(diff),
                        user_id=current_user.id,
                        reason=f"Ajuste automático por conteo físico ({diff:.2f})"
                    )

            db.session.commit()
            flash(f"Conteo físico para '{product.name}' actualizado a {new_physical:.2f}.", "success")
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")

        return redirect(url_for('inventory.audit'))

    products = Product.query.filter_by(is_active=True).order_by(Product.code.asc()).all()
    return render_template('inventory/audit.html', products=products)
