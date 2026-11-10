import json
from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, current_app, abort
from flask_login import login_required, current_user
from extensions import db
from models import Receipt, AuditLog, Sale, Purchase, Payment, PurchasePayment
from services.receipt_service import ReceiptService
from services.telegram_service import TelegramService

receipts_bp = Blueprint('receipts', __name__, url_prefix='/receipts')


def resolve_receipt_or_404(id):
    """
    Finds a receipt by Receipt.id. If not found, checks related_sale_id,
    related_purchase_id, related_payment_id, or Sale.id (generating a receipt if missing).
    Raises 404 only if no related entity exists at all.
    """
    # 1. Direct Receipt ID lookup
    receipt = Receipt.query.get(id)
    if receipt:
        return receipt

    # 2. Lookup by related_sale_id
    receipt = Receipt.query.filter_by(related_sale_id=id).first()
    if receipt:
        return receipt

    # 3. Lookup by related_purchase_id
    receipt = Receipt.query.filter_by(related_purchase_id=id).first()
    if receipt:
        return receipt

    # 4. Lookup by related_payment_id
    receipt = Receipt.query.filter_by(related_payment_id=id).first()
    if receipt:
        return receipt

    # 5. Check if id matches a Sale ID that has no receipt yet
    sale = Sale.query.get(id)
    if sale:
        items_payload = [{
            'code': item.product_code_snapshot or (item.product.code if item.product else ''),
            'name': item.product_name_snapshot or (item.product.name if item.product else ''),
            'quantity': float(item.quantity or 0),
            'unit_price': float(item.unit_price or 0.0),
            'discount_percent': float(item.discount_percent or 0.0),
            'discount_amount': float(item.discount_amount or 0.0),
            'tax_applied': item.tax_applied,
            'total': float(item.total or 0.0)
        } for item in sale.items]

        receipt = Receipt(
            receipt_number=f"FACT-{sale.invoice_number}",
            receipt_type='Venta',
            related_sale_id=sale.id,
            client_id=sale.client_id,
            user_id=sale.user_id,
            client_name_snapshot=sale.client_name,
            client_ruc_snapshot=sale.client_ruc,
            client_address_snapshot=sale.client_address,
            salesperson_snapshot=sale.salesperson,
            client_code_snapshot=sale.client_code,
            subtotal=round(sale.subtotal or 0.0, 2),
            discount_amount=round(sale.discount_amount or 0.0, 2),
            tax_amount=round(sale.tax_amount or 0.0, 2),
            total_amount=round(sale.total or 0.0, 2),
            payment_method=sale.payment_method or 'Efectivo',
            payment_condition=sale.payment_condition or 'Contado',
            status='anulado' if sale.status == 'anulada' else 'confirmado',
            notes=sale.notes,
            payload_json=json.dumps({
                'invoice_number': sale.invoice_number,
                'client_name': sale.client_name,
                'client_ruc': sale.client_ruc,
                'client_address': sale.client_address,
                'client_code': sale.client_code,
                'salesperson': sale.salesperson,
                'payment_method': sale.payment_method,
                'payment_condition': sale.payment_condition,
                'subtotal': round(sale.subtotal or 0.0, 2),
                'discount_amount': round(sale.discount_amount or 0.0, 2),
                'tax_amount': round(sale.tax_amount or 0.0, 2),
                'tax_percent': round(sale.tax_percent or 0.0, 2),
                'total': round(sale.total or 0.0, 2),
                'paid_amount': round(sale.paid_amount or 0.0, 2),
                'balance_due': round(sale.balance_due, 2),
                'due_date': sale.due_date.strftime('%Y-%m-%d') if sale.due_date else None,
                'notes': sale.notes,
                'date': sale.created_at.strftime('%Y-%m-%d %H:%M:%S') if sale.created_at else None,
                'items': items_payload
            }, ensure_ascii=False),
            created_at=sale.created_at or datetime.utcnow()
        )
        db.session.add(receipt)
        db.session.commit()
        return receipt

    abort(404)

@receipts_bp.route('/')
@login_required
def index():
    receipt_num = request.args.get('receipt_number', '').strip()
    client_name = request.args.get('client_name', '').strip()
    r_type = request.args.get('type', '').strip()
    payment_method = request.args.get('payment_method', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    query = Receipt.query

    if receipt_num:
        query = query.filter(Receipt.receipt_number.ilike(f"%{receipt_num}%"))
    if client_name:
        query = query.filter(Receipt.client_name_snapshot.ilike(f"%{client_name}%"))
    if r_type:
        query = query.filter_by(receipt_type=r_type)
    if payment_method:
        query = query.filter_by(payment_method=payment_method)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Receipt.created_at >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d')
            ed = datetime.combine(ed.date(), datetime.max.time())
            query = query.filter(Receipt.created_at <= ed)
        except ValueError:
            pass

    receipts = query.order_by(Receipt.created_at.desc()).limit(150).all()

    receipt_types = ['Venta', 'Compra', 'Abono', 'Pago_Proveedor', 'Devolucion_Cliente', 'Devolucion_Proveedor', 'Entrada_Inventario', 'Salida_Inventario', 'Ingreso', 'Gasto', 'Ajuste']

    return render_template(
        'receipts/index.html',
        receipts=receipts,
        receipt_types=receipt_types,
        selected_number=receipt_num,
        selected_client=client_name,
        selected_type=r_type,
        selected_payment=payment_method,
        start_date=start_date,
        end_date=end_date
    )

@receipts_bp.route('/<int:id>')
@login_required
def view_receipt(id):
    receipt = resolve_receipt_or_404(id)
    return render_template('receipts/view.html', receipt=receipt)

@receipts_bp.route('/sale/<int:sale_id>')
@login_required
def view_sale(sale_id):
    receipt = resolve_receipt_or_404(sale_id)
    return redirect(url_for('receipts.view_receipt', id=receipt.id))

@receipts_bp.route('/invoice/<path:invoice_number>')
@login_required
def view_invoice(invoice_number):
    inv = invoice_number.strip().lstrip('#')
    # Try direct receipt number
    receipt = Receipt.query.filter(
        db.or_(
            Receipt.receipt_number == inv,
            Receipt.receipt_number == f"FACT-{inv}",
            Receipt.receipt_number.ilike(f"%{inv}%")
        )
    ).first()
    if receipt:
        return redirect(url_for('receipts.view_receipt', id=receipt.id))

    sale = Sale.query.filter(Sale.invoice_number.ilike(inv)).first()
    if sale:
        receipt = resolve_receipt_or_404(sale.id)
        return redirect(url_for('receipts.view_receipt', id=receipt.id))

    flash(f"No se encontró comprobante ni factura para #{inv}.", "warning")
    return redirect(url_for('receipts.index'))

@receipts_bp.route('/<int:id>/print')
@login_required
def print_receipt(id):
    receipt = resolve_receipt_or_404(id)
    return render_template('receipts/invoice_print.html', receipt=receipt)

@receipts_bp.route('/<int:id>/pdf')
@login_required
def download_pdf(id):
    receipt = resolve_receipt_or_404(id)
    pdf_buffer = ReceiptService.generate_receipt_pdf(receipt)
    filename = f"Factura_{receipt.receipt_number.replace('/', '_')}.pdf"
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )

@receipts_bp.route('/<int:id>/telegram', methods=['POST'])
@login_required
def send_telegram(id):
    receipt = resolve_receipt_or_404(id)
    cfg = TelegramService.get_config()
    if not cfg['enabled'] or not cfg['bot_token'] or not cfg['chat_id']:
        flash("La integración de Telegram no está configurada o se encuentra desactivada.", "warning")
        return redirect(url_for('receipts.view_receipt', id=id))

    currency = current_app.config.get('COMPANY_CURRENCY', 'C$')
    text = (
        f"📄 <b>COMPROBANTE CITYPET PHARMA</b>\n"
        f"<b>Factura:</b> #{receipt.receipt_number}\n"
        f"<b>Tipo:</b> {receipt.receipt_type}\n"
        f"<b>Cliente:</b> {receipt.client_name_snapshot or 'Consumidor Final'}\n"
        f"<b>Fecha:</b> {receipt.created_at.strftime('%d/%m/%Y %H:%M') if receipt.created_at else ''}\n"
        f"<b>Total:</b> {currency} {float(receipt.total_amount or 0.0):,.2f}\n"
        f"<b>Estado:</b> {receipt.status.upper()}"
    )

    success, msg = TelegramService.send_raw_message(cfg['bot_token'], cfg['chat_id'], text)
    if success:
        flash("Comprobante enviado por Telegram exitosamente.", "success")
    else:
        flash(f"Error al enviar por Telegram: {msg}", "danger")

    return redirect(url_for('receipts.view_receipt', id=id))
