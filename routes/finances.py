from datetime import datetime, date
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, current_app
from flask_login import login_required, current_user
from extensions import db
from models import FinancialMovement, AuditLog
from routes.auth import admin_required

finances_bp = Blueprint('finances', __name__, url_prefix='/finances')

@finances_bp.route('/')
@login_required
@admin_required
def index():
    mov_type = request.args.get('type', '').strip()
    category = request.args.get('category', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    query = FinancialMovement.query

    if mov_type:
        query = query.filter_by(movement_type=mov_type)
    if category:
        query = query.filter_by(category=category)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(FinancialMovement.date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(FinancialMovement.date <= ed)
        except ValueError:
            pass

    movements = query.order_by(FinancialMovement.date.desc(), FinancialMovement.id.desc()).limit(200).all()

    total_incomes = sum(m.amount for m in movements if m.movement_type == 'Ingreso')
    total_expenses = sum(m.amount for m in movements if m.movement_type == 'Gasto')
    net_flow = total_incomes - total_expenses

    categories = [
        'Venta', 'Compra de Mercancía', 'Servicios Básicos (Luz/Agua/Internet)',
        'Alquiler de Local', 'Salarios y Comisiones', 'Transporte y Envíos',
        'Mantenimiento y Equipamiento', 'Publicidad y Marketing',
        'Ajuste de Caja Chica', 'Otro Ingreso', 'Otro Gasto'
    ]

    return render_template(
        'finances/index.html',
        movements=movements,
        total_incomes=total_incomes,
        total_expenses=total_expenses,
        net_flow=net_flow,
        categories=categories,
        selected_type=mov_type,
        selected_category=category,
        start_date=start_date,
        end_date=end_date
    )

@finances_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create():
    mov_type = request.form.get('movement_type', '').strip()
    category = request.form.get('category', '').strip()
    description = request.form.get('description', '').strip()
    payment_method = request.form.get('payment_method', 'Efectivo').strip()
    raw_date = request.form.get('date', '').strip()

    try:
        amount = abs(float(request.form.get('amount') or 0.0))
    except ValueError:
        amount = 0.0

    if not mov_type or not category or not description or amount <= 0:
        flash("Datos incompletos o monto inválido para el movimiento financiero.", "danger")
        return redirect(url_for('finances.index'))

    if raw_date:
        try:
            mov_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            mov_date = date.today()
    else:
        mov_date = date.today()

    last_f = FinancialMovement.query.order_by(FinancialMovement.id.desc()).first()
    next_num = (last_f.id + 1) if last_f else 1
    code = f"FIN-{mov_type[:3].upper()}-{next_num:05d}"

    movement = FinancialMovement(
        code=code,
        movement_type=mov_type,
        category=category,
        amount=amount,
        payment_method=payment_method,
        description=description,
        user_id=current_user.id,
        date=mov_date,
        created_at=datetime.utcnow()
    )
    db.session.add(movement)

    audit = AuditLog(
        user_id=current_user.id,
        action='CREATE_FINANCIAL_MOVEMENT',
        entity_type='FinancialMovement',
        entity_id=code,
        details=f"Movimiento {mov_type}: {category} por C$ {amount:,.2f} - {description}"
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Movimiento financiero {code} registrado con éxito.", "success")
    return redirect(url_for('finances.index'))

@finances_bp.route('/<int:id>/void', methods=['POST'])
@login_required
@admin_required
def void(id):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Debe proporcionar un motivo para anular el movimiento.", "warning")
        return redirect(url_for('finances.index'))

    mov = FinancialMovement.query.get_or_404(id)
    if mov.status == 'anulado':
        flash("El movimiento ya se encuentra anulado.", "warning")
        return redirect(url_for('finances.index'))

    mov.status = 'anulado'
    mov.void_reason = reason
    mov.voided_by_id = current_user.id
    mov.voided_at = datetime.utcnow()

    audit = AuditLog(
        user_id=current_user.id,
        action='VOID_FINANCIAL_MOVEMENT',
        entity_type='FinancialMovement',
        entity_id=mov.code,
        details=f"Movimiento {mov.code} anulado. Motivo: {reason}"
    )
    db.session.add(audit)
    db.session.commit()
    flash(f"Movimiento {mov.code} anulado correctamente.", "info")
    return redirect(url_for('finances.index'))

@finances_bp.route('/export/excel')
@login_required
@admin_required
def export_excel():
    """Exports financial movements to Excel (.xlsx)."""
    mov_type = request.args.get('type', '').strip()
    category = request.args.get('category', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    query = FinancialMovement.query
    if mov_type: query = query.filter_by(movement_type=mov_type)
    if category: query = query.filter_by(category=category)
    if start_date:
        try: query = query.filter(FinancialMovement.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        except ValueError: pass
    if end_date:
        try: query = query.filter(FinancialMovement.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        except ValueError: pass

    movements = query.order_by(FinancialMovement.date.desc(), FinancialMovement.id.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Movimientos Dinero"

    # Styling
    header_fill = PatternFill(start_color="1B4965", end_color="1B4965", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Segoe UI", size=14, bold=True, color="1B4965")
    border_thin = Border(left=Side(style='thin', color='E2E8F0'),
                         right=Side(style='thin', color='E2E8F0'),
                         top=Side(style='thin', color='E2E8F0'),
                         bottom=Side(style='thin', color='E2E8F0'))

    ws.merge_cells('A1:H1')
    ws['A1'] = "CITYPET PHARMA — REPORTE DE MOVIMIENTOS FINANCIEROS Y CAJA"
    ws['A1'].font = title_font
    ws['A1'].alignment = Alignment(horizontal='center')

    ws['A2'] = f"Generado: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC | Usuario: {current_user.username}"
    ws['A2'].font = Font(name="Segoe UI", size=9, italic=True)

    headers = ["Código", "Fecha", "Tipo", "Categoría", "Descripción", "Método de Pago", "Monto (C$)", "Registrado Por"]
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center' if col_idx in (1, 2, 3, 6) else 'left')

    row_num = 5
    tot_in = 0.0
    tot_out = 0.0

    for m in movements:
        if m.status != 'anulado':
            if m.movement_type == 'Ingreso': tot_in += m.amount
            elif m.movement_type == 'Gasto': tot_out += m.amount

        ws.cell(row=row_num, column=1, value=m.code).alignment = Alignment(horizontal='center')
        ws.cell(row=row_num, column=2, value=m.date.strftime('%d/%m/%Y')).alignment = Alignment(horizontal='center')
        ws.cell(row=row_num, column=3, value=m.movement_type).alignment = Alignment(horizontal='center')
        ws.cell(row=row_num, column=4, value=m.category)
        ws.cell(row=row_num, column=5, value=m.description or '')
        ws.cell(row=row_num, column=6, value=m.payment_method or '').alignment = Alignment(horizontal='center')
        
        amt_cell = ws.cell(row=row_num, column=7, value=m.amount)
        amt_cell.number_format = '#,##0.00'
        amt_cell.alignment = Alignment(horizontal='right')
        
        ws.cell(row=row_num, column=8, value=m.user.full_name if m.user else 'Sistema')

        for c in range(1, 9):
            ws.cell(row=row_num, column=c).border = border_thin
        row_num += 1

    # Totals Row
    ws.cell(row=row_num + 1, column=5, value="Total Ingresos:").font = Font(bold=True)
    in_cell = ws.cell(row=row_num + 1, column=7, value=tot_in)
    in_cell.font = Font(bold=True, color="166534")
    in_cell.number_format = '#,##0.00'

    ws.cell(row=row_num + 2, column=5, value="Total Gastos:").font = Font(bold=True)
    out_cell = ws.cell(row=row_num + 2, column=7, value=tot_out)
    out_cell.font = Font(bold=True, color="991B1B")
    out_cell.number_format = '#,##0.00'

    ws.cell(row=row_num + 3, column=5, value="Flujo Neto:").font = Font(bold=True)
    net_cell = ws.cell(row=row_num + 3, column=7, value=tot_in - tot_out)
    net_cell.font = Font(bold=True, color="0A3D69")
    net_cell.number_format = '#,##0.00'

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"CityPet_Movimientos_Finanzas_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@finances_bp.route('/export/pdf')
@login_required
@admin_required
def export_pdf():
    """Exports financial movements to PDF report."""
    mov_type = request.args.get('type', '').strip()
    category = request.args.get('category', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    query = FinancialMovement.query
    if mov_type: query = query.filter_by(movement_type=mov_type)
    if category: query = query.filter_by(category=category)
    if start_date:
        try: query = query.filter(FinancialMovement.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        except ValueError: pass
    if end_date:
        try: query = query.filter(FinancialMovement.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        except ValueError: pass

    movements = query.order_by(FinancialMovement.date.desc(), FinancialMovement.id.desc()).all()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter), leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()

    elements = []
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1B4965'), alignment=1, spaceAfter=4)
    subtitle_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#64748B'), alignment=1, spaceAfter=14)

    elements.append(Paragraph("<b>CITYPET PHARMA — REPORTE DE MOVIMIENTOS FINANCIEROS Y FLUJO DE CAJA</b>", title_style))
    elements.append(Paragraph(f"Emitido el: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC | Usuario: {current_user.full_name}", subtitle_style))

    tot_in = sum(m.amount for m in movements if m.movement_type == 'Ingreso' and m.status != 'anulado')
    tot_out = sum(m.amount for m in movements if m.movement_type == 'Gasto' and m.status != 'anulado')
    net_val = tot_in - tot_out

    summary_data = [
        ["Total Ingresos Registrados:", f"C$ {tot_in:,.2f}", "Total Gastos Operativos:", f"C$ {tot_out:,.2f}", "Flujo Neto:", f"C$ {net_val:,.2f}"]
    ]
    t_summary = Table(summary_data, colWidths=[2.2*inch, 1.4*inch, 2.2*inch, 1.4*inch, 1.2*inch, 1.6*inch])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
        ('TEXTCOLOR', (1, 0), (1, 0), colors.HexColor('#166534')),
        ('TEXTCOLOR', (3, 0), (3, 0), colors.HexColor('#991B1B')),
        ('TEXTCOLOR', (5, 0), (5, 0), colors.HexColor('#1B4965')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 12))

    table_data = [["Código", "Fecha", "Tipo", "Categoría", "Descripción", "Método", "Monto", "Registrado Por"]]
    for m in movements[:80]:
        table_data.append([
            m.code,
            m.date.strftime('%d/%m/%Y'),
            m.movement_type,
            m.category,
            (m.description[:35] + '...') if len(m.description or '') > 35 else (m.description or ''),
            m.payment_method or '',
            f"C$ {m.amount:,.2f}",
            (m.user.username if m.user else 'Sistema')
        ])

    col_widths = [1.2*inch, 0.9*inch, 0.8*inch, 1.8*inch, 2.5*inch, 1.0*inch, 1.1*inch, 1.1*inch]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B4965')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (0, 0), (2, -1), 'CENTER'),
        ('ALIGN', (6, 0), (6, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)

    doc.build(elements)
    buf.seek(0)
    filename = f"CityPet_Movimientos_Finanzas_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype="application/pdf")
