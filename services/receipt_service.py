import os
from io import BytesIO
from datetime import datetime
from flask import current_app
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from models import Receipt

class ReceiptService:
    @staticmethod
    def generate_receipt_pdf(receipt):
        """
        Builds a high-fidelity PDF corresponding to City Pet Pharma _ Factura.pdf layout.
        Uses reportlab to generate the document buffer.
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'InvoiceTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#0F5B9E'),
            alignment=1
        )
        small_info = ParagraphStyle(
            'CompanyInfo',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#333333')
        )
        bold_info = ParagraphStyle(
            'BoldCompanyInfo',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=11,
            textColor=colors.HexColor('#111111')
        )
        table_hdr_style = ParagraphStyle(
            'TableHdr',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=11,
            textColor=colors.white,
            alignment=1
        )
        cell_style = ParagraphStyle(
            'CellText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#222222')
        )
        cell_right = ParagraphStyle(
            'CellRight',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#222222'),
            alignment=2
        )

        elements = []

        # 1. Header Row: Logo on Left, Company Box on Right
        logo_path = os.path.join(current_app.root_path, 'static', 'img', 'citypet_logo_whitebg.png')
        if not os.path.exists(logo_path):
            logo_path = os.path.join(current_app.root_path, 'static', 'img', 'citypet_logo.png')

        logo_img = None
        if os.path.exists(logo_path):
            logo_img = Image(logo_path, width=1.8 * inch, height=0.8 * inch)
            logo_img.hAlign = 'LEFT'
        else:
            logo_img = Paragraph("<b>CITYPET PHARMA</b>", title_style)

        company_box_data = [
            [Paragraph("<b>RUC: 0010712900023W</b>", bold_info)],
            [Paragraph("Dirección: Col. Cristian Pérez, ddf el Cine Rex 50 vrs. al Norte", small_info)],
            [Paragraph("Tel.: (+505) 8363-7606", small_info)]
        ]
        company_table = Table(company_box_data, colWidths=[3.2 * inch])
        company_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#EBF3F5')),
            ('PADDING', (0,0), (-1,-1), 6),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#C8D6DF')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))

        header_table = Table([
            [logo_img, company_table]
        ], colWidths=[3.8 * inch, 3.4 * inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        elements.append(header_table)

        # 2. Document Title and Number
        doc_type_map = {
            'Venta': 'FACTURA',
            'Compra': 'COMPROBANTE DE COMPRA',
            'Abono': 'RECIBO DE CAJA / ABONO',
            'Pago_Proveedor': 'COMPROBANTE DE PAGO A PROVEEDOR',
            'Devolucion_Cliente': 'NOTA DE CRÉDITO / DEVOLUCIÓN',
            'Devolucion_Proveedor': 'DEVOLUCIÓN A PROVEEDOR'
        }
        doc_title = doc_type_map.get(receipt.receipt_type, 'COMPROBANTE')
        invoice_num = (receipt.receipt_number or '').replace('FACT-', '')
        factura_title_table = Table([
            [Paragraph(f"<b>{doc_title}</b>", title_style),
             Paragraph(f"<b>Nº {invoice_num}</b>", ParagraphStyle('InvNum', parent=title_style, fontSize=14, textColor=colors.HexColor('#222222'), alignment=2))]
        ], colWidths=[4.5 * inch, 2.7 * inch])
        elements.append(factura_title_table)
        elements.append(Spacer(1, 6))

        # 3. Client and Meta details Box
        date_str = receipt.created_at.strftime('%d / %m / %Y') if receipt.created_at else ''
        client_box_data = [
            [Paragraph(f"<b>Cliente:</b> {receipt.client_name_snapshot or 'Consumidor Final'}", cell_style),
             Paragraph(f"<b>Nº Factura:</b> {invoice_num}", cell_style)],
            [Paragraph(f"<b>Ruc:</b> {receipt.client_ruc_snapshot or 'N/A'}", cell_style),
             Paragraph(f"<b>Fecha:</b> {date_str}", cell_style)],
            [Paragraph(f"<b>Dirección:</b> {receipt.client_address_snapshot or 'Ciudad'}", cell_style),
             Paragraph(f"<b>Pago:</b> {receipt.payment_method or 'Efectivo'} ({receipt.payment_condition or 'Contado'})", cell_style)],
            [Paragraph(f"<b>Vendedor:</b> {receipt.salesperson_snapshot or 'Mostrador'}", cell_style),
             Paragraph(f"<b>Código cliente:</b> {receipt.client_code_snapshot or 'N/A'}", cell_style)]
        ]
        client_table = Table(client_box_data, colWidths=[4.6 * inch, 2.6 * inch])
        client_table.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#0F5B9E')),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('PADDING', (0,0), (-1,-1), 5),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LINEBELOW', (0,0), (-1,-2), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        elements.append(client_table)
        elements.append(Spacer(1, 10))

        # 4. Items Table
        items_headers = [
            Paragraph("Código", table_hdr_style),
            Paragraph("Producto", table_hdr_style),
            Paragraph("Cantidad", table_hdr_style),
            Paragraph("Precio Unitario", table_hdr_style),
            Paragraph("DSCTO.", table_hdr_style),
            Paragraph("Total", table_hdr_style)
        ]
        table_rows = [items_headers]

        payload = receipt.payload
        items = payload.get('items', [])
        currency = current_app.config.get('COMPANY_CURRENCY', 'C$')

        for item in items:
            c_code = Paragraph(str(item.get('code', '') or ''), cell_style)
            c_name = Paragraph(str(item.get('name', '') or ''), cell_style)
            qty_val = float(item.get('quantity') or 0.0)
            c_qty = Paragraph(f"{qty_val:.0f}", cell_right)
            unit_price_val = float(item.get('unit_price') or item.get('unit_cost') or 0.0)
            c_price = Paragraph(f"{currency} {unit_price_val:,.2f}", cell_right)
            dscto_val = float(item.get('discount_percent') or 0.0)
            c_dscto = Paragraph(f"{dscto_val:.0f}%", cell_right)
            total_val = float(item.get('total') or (qty_val * unit_price_val * (1.0 - dscto_val / 100.0)))
            c_total = Paragraph(f"{currency} {total_val:,.2f}", cell_right)
            table_rows.append([c_code, c_name, c_qty, c_price, c_dscto, c_total])

        # Fill min 5 rows if few items for realistic paper invoice look
        while len(table_rows) < 6:
            table_rows.append([Paragraph("", cell_style) for _ in range(6)])

        items_col_widths = [1.0 * inch, 2.7 * inch, 0.7 * inch, 1.1 * inch, 0.7 * inch, 1.0 * inch]
        items_table = Table(table_rows, colWidths=items_col_widths)
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F5B9E')),
            ('PADDING', (0,0), (-1,-1), 4),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 6))

        # 5. Totals Block
        subtotal = float(receipt.subtotal or 0.0)
        total = float(receipt.total_amount or 0.0)
        discount = float(receipt.discount_amount or 0.0)

        totals_data = [
            [Paragraph("<b>CUOTA FIJA</b>", ParagraphStyle('CF', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0F5B9E'))),
             Paragraph("<b>SUBTOTAL:</b>", cell_right),
             Paragraph(f"{currency} {subtotal:,.2f}", cell_right)],
            ["",
             Paragraph("<b>DESCUENTO:</b>", cell_right),
             Paragraph(f"{currency} {discount:,.2f}", cell_right)],
            ["",
             Paragraph("<b>TOTAL:</b>", ParagraphStyle('TotLbl', parent=cell_right, fontName='Helvetica-Bold', textColor=colors.white)),
             Paragraph(f"<b>{currency} {total:,.2f}</b>", ParagraphStyle('TotVal', parent=cell_right, fontName='Helvetica-Bold', textColor=colors.white))]
        ]
        totals_table = Table(totals_data, colWidths=[3.7 * inch, 1.8 * inch, 1.7 * inch])
        totals_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,0), colors.HexColor('#EFF6FF')),
            ('BOX', (0,0), (0,0), 1, colors.HexColor('#0F5B9E')),
            ('BACKGROUND', (1,2), (2,2), colors.HexColor('#0F5B9E')),
            ('PADDING', (0,0), (-1,-1), 3),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(totals_table)
        elements.append(Spacer(1, 14))

        # 6. Signatures Box
        sig_data = [
            [Paragraph("<b>Entregué conforme</b>", cell_style), Paragraph("<b>Recibí conforme</b>", cell_style)],
            [Spacer(1, 20), Spacer(1, 20)],
            [Paragraph("____________________________________<br/>Nombre y Nº cédula:", cell_style),
             Paragraph("____________________________________<br/>Nombre y Nº cédula:", cell_style)]
        ]
        sig_table = Table(sig_data, colWidths=[3.6 * inch, 3.6 * inch])
        sig_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('PADDING', (0,0), (-1,-1), 6),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ]))
        elements.append(sig_table)
        elements.append(Spacer(1, 10))

        # 7. Legal Promissory Note Clause (From Page 2 of original document)
        legal_text = (
            "<b>Pagaré / Compromiso:</b> Yo _______________________________________ Acepto deber a "
            "<b>Marbelly Mejía Espinoza</b> la cantidad expresada en este documento, la cual me comprometo a "
            "cancelar en tiempo y forma; de lo contrario, reconoceré la tasa de interés sobre saldo monetario "
            "publicada por el BANCO CENTRAL DE NICARAGUA. Factura cancelada con mantenimiento de valor "
            "conforme Arto. 38 de la Ley 732, Ley Orgánica del BCN."
        )
        legal_p = Paragraph(legal_text, ParagraphStyle('Legal', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=6.5, leading=8, textColor=colors.HexColor('#555555')))
        elements.append(legal_p)

        doc.build(elements)
        buffer.seek(0)
        return buffer
