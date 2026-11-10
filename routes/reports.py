from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, send_file, current_app, jsonify
from flask_login import login_required
from extensions import db
from models import Product, Sale, SaleItem, FinancialMovement, Client, Supplier
from services.report_service import ReportService
from services.excel_service import ExcelService
from services.summary_service import SummaryService, get_managua_today
from routes.auth import admin_required
from io import BytesIO
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')

@reports_bp.route('/')
@login_required
def index():
    report_type = request.args.get('type', 'sales')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    today = get_managua_today()
    if start_date_str:
        try: start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError: start_date = today - timedelta(days=30)
    else:
        start_date = today - timedelta(days=30)

    if end_date_str:
        try: end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError: end_date = today
    else:
        end_date = today

    sales_report = ReportService.get_sales_report(start_date=start_date, end_date=end_date)
    inventory_items = ReportService.get_inventory_audit_report()
    
    total_inventory_value = sum(i['valuation'] for i in inventory_items)
    discrepancy_count = sum(1 for i in inventory_items if i['difference'] != 0)

    return render_template(
        'reports/index.html',
        report_type=report_type,
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'),
        sales_report=sales_report,
        inventory_items=inventory_items,
        total_inventory_value=total_inventory_value,
        discrepancy_count=discrepancy_count
    )

@reports_bp.route('/daily')
@login_required
@admin_required
def daily():
    """Daily operational and commercial summary with Managua timezone."""
    selected_date_str = request.args.get('date', '').strip()
    today = get_managua_today()
    if selected_date_str:
        try:
            target_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = today
    else:
        target_date = today

    summary = SummaryService.get_daily_summary(target_date)
    return render_template('reports/daily.html', summary=summary, selected_date=target_date.strftime('%Y-%m-%d'))

@reports_bp.route('/monthly')
@login_required
@admin_required
def monthly():
    """Monthly commercial summary with MoM comparisons and top/least products."""
    today = get_managua_today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)

    summary = SummaryService.get_monthly_summary(year, month)
    years_available = list(range(today.year - 2, today.year + 2))

    return render_template(
        'reports/monthly.html',
        summary=summary,
        selected_year=year,
        selected_month=month,
        years_available=years_available
    )

@reports_bp.route('/trends')
@login_required
def trends():
    """Trends visualization page (7d, 30d, 3m, custom)."""
    period = request.args.get('period', '30d')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    trend_data = SummaryService.get_trend_data(period=period, custom_start=start_date, custom_end=end_date)
    return render_template(
        'reports/trends.html',
        trend_data=trend_data,
        period=period,
        start_date=start_date,
        end_date=end_date
    )

@reports_bp.route('/trends/data')
@login_required
def trends_data():
    """JSON API for time-series charts."""
    period = request.args.get('period', '30d')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    data = SummaryService.get_trend_data(period=period, custom_start=start_date, custom_end=end_date)
    return jsonify(data)

@reports_bp.route('/export/excel')
@login_required
def export_excel():
    report_type = request.args.get('type', 'sales')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    today = get_managua_today()
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else today - timedelta(days=30)
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else today

    if report_type == 'inventory':
        items = ReportService.get_inventory_audit_report()
        headers = ['Código', 'Producto', 'Categoría', 'Stock Sistema', 'Conteo Físico', 'Diferencia', 'Estado', 'Valoración (C$)']
        rows = [
            [i['code'], i['name'], i['category'], i['current_stock'], i['physical_stock'], i['difference'], i['status'], i['valuation']]
            for i in items
        ]
        title = "Inventario y Valoracion"
    else:
        rep = ReportService.get_sales_report(start_date=start_date, end_date=end_date)
        headers = ['Factura', 'Fecha', 'Cliente', 'Vendedor', 'Pago', 'Subtotal', 'Descuento', 'Total (C$)', 'Costo Venta', 'Ganancia']
        rows = []
        for s in rep['sales']:
            profit = s.total - s.cost_of_sales
            rows.append([
                s.invoice_number,
                s.created_at.strftime('%d/%m/%Y'),
                s.client_name,
                s.salesperson or 'Mostrador',
                s.payment_method,
                s.subtotal,
                s.discount_amount,
                s.total,
                s.cost_of_sales,
                round(profit, 2)
            ])
        title = f"Ventas {start_date.strftime('%d%m%Y')} a {end_date.strftime('%d%m%Y')}"

    excel_buffer = ExcelService.export_data_to_excel(title, headers, rows)
    filename = f"{title.replace(' ', '_')}.xlsx"
    return send_file(
        excel_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@reports_bp.route('/export/pdf')
@login_required
def export_pdf():
    report_type = request.args.get('type', 'sales')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    today = get_managua_today()
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else today - timedelta(days=30)
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else today

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()

    elements = []
    title_style = ParagraphStyle('ReportTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#0F5B9E'))
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10)
    hdr_style = ParagraphStyle('Hdr', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.white)

    currency = current_app.config.get('COMPANY_CURRENCY', 'C$')

    if report_type == 'inventory':
        elements.append(Paragraph(f"<b>CITYPET PHARMA — REPORTE DE INVENTARIO Y VALORACIÓN</b>", title_style))
        elements.append(Spacer(1, 10))
        headers = ["Código", "Producto", "Categoría", "Stock Sistema", "Físico", "Dif.", "Estado", "Valoración"]
        table_data = [[Paragraph(h, hdr_style) for h in headers]]
        items = ReportService.get_inventory_audit_report()
        for i in items:
            table_data.append([
                Paragraph(i['code'], cell_style),
                Paragraph(i['name'], cell_style),
                Paragraph(i['category'], cell_style),
                Paragraph(f"{i['current_stock']:.0f}", cell_style),
                Paragraph(f"{i['physical_stock']:.0f}", cell_style),
                Paragraph(f"{i['difference']:.0f}", cell_style),
                Paragraph(i['status'], cell_style),
                Paragraph(f"{currency} {i['valuation']:,.2f}", cell_style),
            ])
        col_widths = [60, 200, 100, 70, 60, 60, 80, 90]
    else:
        elements.append(Paragraph(f"<b>CITYPET PHARMA — REPORTE DE VENTAS ({start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')})</b>", title_style))
        elements.append(Spacer(1, 10))
        headers = ["Factura", "Fecha", "Cliente", "Vendedor", "Pago", "Total", "Costo", "Ganancia"]
        table_data = [[Paragraph(h, hdr_style) for h in headers]]
        rep = ReportService.get_sales_report(start_date=start_date, end_date=end_date)
        for s in rep['sales']:
            profit = s.total - s.cost_of_sales
            table_data.append([
                Paragraph(s.invoice_number, cell_style),
                Paragraph(s.created_at.strftime('%d/%m/%Y'), cell_style),
                Paragraph(s.client_name[:25], cell_style),
                Paragraph(s.salesperson or 'Mostrador', cell_style),
                Paragraph(s.payment_method, cell_style),
                Paragraph(f"{currency} {s.total:,.2f}", cell_style),
                Paragraph(f"{currency} {s.cost_of_sales:,.2f}", cell_style),
                Paragraph(f"{currency} {profit:,.2f}", cell_style)
            ])
        col_widths = [60, 70, 180, 100, 70, 80, 80, 80]

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F5B9E')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)
    filename = f"Reporte_{report_type}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )
