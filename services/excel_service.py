import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from datetime import datetime, date
from io import BytesIO
from extensions import db
from models import Product, Client, Supplier, InventoryMovement, User, AuditLog

class ExcelService:
    @staticmethod
    def parse_sheet_preview(file_stream, max_preview_rows=10):
        """
        Reads an uploaded workbook, lists sheet names, and provides a preview
        of the first rows of each sheet to let the user select and map columns.
        """
        wb = openpyxl.load_workbook(file_stream, data_only=True)
        sheets_info = {}
        for name in wb.sheetnames:
            ws = wb[name]
            rows = []
            for r in range(1, min(ws.max_row + 1, max_preview_rows + 1)):
                row_vals = [ws.cell(r, c).value for c in range(1, min(ws.max_column + 1, 30))]
                if any(v is not None for v in row_vals):
                    rows.append(row_vals)
            sheets_info[name] = {
                'total_rows': ws.max_row,
                'total_cols': ws.max_column,
                'preview_rows': rows
            }
        return sheets_info

    @staticmethod
    def preview_citypet_master_excel(filepath):
        """
        Generates a non-destructive pre-import reconciliation & duplicate detection preview
        for INVENTARIO NUEVO.xlsx before any database write occurs.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Archivo no encontrado en {filepath}")

        wb = openpyxl.load_workbook(filepath, data_only=True)
        preview = {
            'suppliers': {'new': [], 'existing': []},
            'products': {'new': [], 'existing': [], 'omitted': [], 'discrepancies': []},
            'clients': {'new': [], 'existing': [], 'omitted': []},
            'movements': {
                'new_count': 0,
                'duplicates_existing_count': 0,
                'metadata_updates_count': 0,
                'omitted_count': 0,
                'errors': [],
                'by_supplier': {'Novavet': 0, 'CampoVet': 0}
            }
        }

        # 1. Check Suppliers
        for code, comp_name in [('PROV-NOVAVET', 'Novavet'), ('PROV-CAMPOVET', 'CampoVet')]:
            exists = Supplier.query.filter_by(code=code).first()
            if exists:
                preview['suppliers']['existing'].append({'code': code, 'name': comp_name})
            else:
                preview['suppliers']['new'].append({'code': code, 'name': comp_name})

        # 2. Check Products
        existing_prods = {p.code: p for p in Product.query.all()}
        if 'Catalogo Productos' in wb.sheetnames:
            ws_p = wb['Catalogo Productos']
            for r in range(8, ws_p.max_row + 1):
                code = ws_p.cell(r, 2).value
                name = ws_p.cell(r, 3).value
                code_str = str(code or '').strip()
                name_str = str(name or '').strip()

                if not code_str or not name_str or code_str.upper() in ('ANULADO', 'CP000000') or name_str.upper() == 'ANULADO':
                    preview['products']['omitted'].append({
                        'row': r,
                        'code': code_str or f'Fila-{r}',
                        'reason': 'Registro anulado o vacío en catálogo original'
                    })
                    continue

                try: excel_calc = float(ws_p.cell(r, 10).value or 0.0)
                except (ValueError, TypeError): excel_calc = 0.0
                try: excel_phys = float(ws_p.cell(r, 12).value or 0.0)
                except (ValueError, TypeError): excel_phys = 0.0

                item_info = {
                    'row': r,
                    'code': code_str,
                    'name': name_str,
                    'excel_stock': excel_calc,
                    'excel_physical': excel_phys,
                    'diff': round(excel_phys - excel_calc, 2)
                }
                if code_str in existing_prods:
                    preview['products']['existing'].append(item_info)
                else:
                    preview['products']['new'].append(item_info)

                if abs(excel_phys - excel_calc) > 0.001:
                    preview['products']['discrepancies'].append(item_info)

        # 3. Check Clients (recovering rows where Col 3 is empty but Col 2 has trade_name)
        existing_clients = {c.code: c for c in Client.query.all()}
        if 'Clientes' in wb.sheetnames:
            ws_c = wb['Clientes']
            for r in range(5, ws_c.max_row + 1):
                code = ws_c.cell(r, 1).value
                trade_name = ws_c.cell(r, 2).value
                full_name = ws_c.cell(r, 3).value

                code_clean = str(code or '').strip()
                trade_clean = str(trade_name or '').strip()
                full_clean = str(full_name or '').strip()

                effective_name = full_clean if full_clean else trade_clean

                if not code_clean or not effective_name or code_clean.upper() == 'CP-C0000' or effective_name.upper() == 'ANULADO':
                    preview['clients']['omitted'].append({
                        'row': r,
                        'code': code_clean or f'Fila-{r}',
                        'reason': 'Registro anulado o código reservado sin cliente'
                    })
                    continue

                c_info = {
                    'row': r,
                    'code': code_clean,
                    'trade_name': trade_clean or effective_name,
                    'name': effective_name,
                    'recovered_from_trade_name': (not bool(full_clean) and bool(trade_clean))
                }
                if code_clean in existing_clients:
                    preview['clients']['existing'].append(c_info)
                else:
                    preview['clients']['new'].append(c_info)

        # 4. Check Movements
        existing_mov_codes = set(r[0] for r in db.session.query(InventoryMovement.code).filter(InventoryMovement.code.like('MOV-HIST-%')).all())
        valid_prod_codes = set(existing_prods.keys()) | set(p['code'] for p in preview['products']['new'])

        if 'REGISTRO Entradas - Salidas' in wb.sheetnames:
            ws_m = wb['REGISTRO Entradas - Salidas']
            for r in range(8, ws_m.max_row + 1):
                prod_code = ws_m.cell(r, 3).value
                origen = ws_m.cell(r, 7).value
                raw_qty = ws_m.cell(r, 10).value
                if not prod_code or not origen or raw_qty is None:
                    preview['movements']['omitted_count'] += 1
                    continue

                prod_code_clean = str(prod_code).strip()
                if prod_code_clean not in valid_prod_codes:
                    preview['movements']['errors'].append(f"Fila {r}: Producto {prod_code_clean} no válido")
                    continue

                orig_clean = str(origen).strip()
                c12 = str(ws_m.cell(r, 12).value or '').strip()
                c13 = str(ws_m.cell(r, 13).value or '').strip()
                if orig_clean == 'Compra':
                    if 'campo' in c12.lower() or 'campo' in c13.lower():
                        preview['movements']['by_supplier']['CampoVet'] += 1
                    else:
                        preview['movements']['by_supplier']['Novavet'] += 1

                mov_code = f"MOV-HIST-{r:05d}"
                if mov_code in existing_mov_codes:
                    preview['movements']['duplicates_existing_count'] += 1
                    preview['movements']['metadata_updates_count'] += 1
                else:
                    preview['movements']['new_count'] += 1

        return preview

    @staticmethod
    def import_citypet_master_excel(filepath, user_id=None):
        """
        Transactional, idempotent import & reconciliation of INVENTARIO NUEVO.xlsx:
        1. Registers both suppliers: Novavet (PROV-NOVAVET) and CampoVet (PROV-CAMPOVET).
        2. Imports 38 valid products (Catalogo Productos) preserving operational stock if already existing.
        3. Imports all 341 valid clients (including the 10 clients with name in Col 2 'Solo Razón social').
        4. Imports/updates 2,690 historical movements (REGISTRO Entradas - Salidas) with duplicate protection,
           linking CampoVet purchases to CampoVet and preserving IVA, discounts, payment condition, and due date.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Archivo no encontrado en {filepath}")

        wb = openpyxl.load_workbook(filepath, data_only=True)
        report = {
            'suppliers_created': 0,
            'suppliers_updated': 0,
            'products_created': 0,
            'products_updated': 0,
            'clients_created': 0,
            'clients_updated': 0,
            'clients_recovered': 0,
            'movements_imported': 0,
            'movements_enriched': 0,
            'duplicates_skipped': 0,
            'campovet_movements': 0,
            'novavet_movements': 0,
            'errors': []
        }

        # 1. Create / verify Suppliers: Novavet AND CampoVet
        novavet = Supplier.query.filter_by(code='PROV-NOVAVET').first()
        if not novavet:
            novavet = Supplier(
                code='PROV-NOVAVET',
                company_name='Novavet',
                contact_name='Representante Novavet',
                phone='',
                email='',
                notes='Proveedor de productos veterinarios y farmacéuticos'
            )
            db.session.add(novavet)
            db.session.flush()
            report['suppliers_created'] += 1
        else:
            report['suppliers_updated'] += 1

        campovet = Supplier.query.filter_by(code='PROV-CAMPOVET').first()
        if not campovet:
            campovet = Supplier(
                code='PROV-CAMPOVET',
                company_name='CampoVet',
                contact_name='Representante CampoVet',
                phone='',
                email='',
                notes='Proveedor de medicamentos y suministros veterinarios'
            )
            db.session.add(campovet)
            db.session.flush()
            report['suppliers_created'] += 1
        else:
            report['suppliers_updated'] += 1

        # 2. Import Products from 'Catalogo Productos'
        if 'Catalogo Productos' in wb.sheetnames:
            ws_p = wb['Catalogo Productos']
            for r in range(8, ws_p.max_row + 1):
                code = ws_p.cell(r, 2).value
                name = ws_p.cell(r, 3).value
                if not code or not name or str(code).strip().upper() in ['ANULADO', 'CP000000'] or str(name).strip().upper() == 'ANULADO':
                    continue

                code_clean = str(code).strip()
                name_clean = str(name).strip()
                cat = str(ws_p.cell(r, 4).value or 'General').strip()
                warehouse = str(ws_p.cell(r, 5).value or 'Principal').strip()
                unit = str(ws_p.cell(r, 6).value or 'Unid').strip()
                
                try: min_stock = float(ws_p.cell(r, 9).value or 5.0)
                except (ValueError, TypeError): min_stock = 5.0

                try: current_stock = float(ws_p.cell(r, 10).value or 0.0)
                except (ValueError, TypeError): current_stock = 0.0

                try: sale_price = float(ws_p.cell(r, 11).value or 0.0)
                except (ValueError, TypeError): sale_price = 0.0

                try: physical_stock = float(ws_p.cell(r, 12).value or 0.0)
                except (ValueError, TypeError): physical_stock = 0.0

                prod = Product.query.filter_by(code=code_clean).first()
                if not prod:
                    prod = Product(
                        code=code_clean,
                        name=name_clean,
                        category=cat,
                        warehouse=warehouse,
                        unit=unit,
                        min_stock=min_stock,
                        current_stock=max(0.0, current_stock),
                        sale_price=sale_price,
                        physical_stock=physical_stock,
                        supplier_id=novavet.id,
                        is_active=True
                    )
                    db.session.add(prod)
                    report['products_created'] += 1
                else:
                    prod.name = name_clean
                    prod.category = cat
                    prod.warehouse = warehouse
                    prod.unit = unit
                    prod.min_stock = min_stock
                    prod.sale_price = sale_price
                    # Do NOT overwrite current_stock on existing products to protect operational integrity
                    report['products_updated'] += 1

            db.session.flush()

        # 3. Import Clients from 'Clientes' (Including the 10 clients with trade_name in Col 2 and empty Col 3)
        if 'Clientes' in wb.sheetnames:
            ws_c = wb['Clientes']
            for r in range(5, ws_c.max_row + 1):
                code = ws_c.cell(r, 1).value
                trade_name = ws_c.cell(r, 2).value
                full_name = ws_c.cell(r, 3).value

                code_clean = str(code or '').strip()
                trade_clean = str(trade_name or '').strip()
                full_clean = str(full_name or '').strip()

                # Fallback to trade_clean when full_clean is empty!
                effective_name = full_clean if full_clean else trade_clean
                effective_trade = trade_clean if trade_clean else effective_name

                if not code_clean or not effective_name or code_clean.upper() == 'CP-C0000' or effective_name.upper() == 'ANULADO':
                    continue

                owner = str(ws_c.cell(r, 4).value or '').strip()
                dept = str(ws_c.cell(r, 5).value or '').strip()
                muni = str(ws_c.cell(r, 6).value or '').strip()
                address = str(ws_c.cell(r, 7).value or '').strip()
                ruc = str(ws_c.cell(r, 8).value or '').strip()
                phone = str(ws_c.cell(r, 9).value or '').strip()
                salesperson = str(ws_c.cell(r, 10).value or '').strip()
                matricula = str(ws_c.cell(r, 11).value or '').strip()
                
                try: credit_limit = float(ws_c.cell(r, 12).value or 0.0)
                except (ValueError, TypeError): credit_limit = 0.0

                term_code = str(ws_c.cell(r, 13).value or '').strip()
                
                try: credit_days = int(ws_c.cell(r, 14).value or 0)
                except (ValueError, TypeError): credit_days = 0

                transport = str(ws_c.cell(r, 15).value or '').strip()
                cond = str(ws_c.cell(r, 16).value or '').strip()

                client = Client.query.filter_by(code=code_clean).first()
                if not client:
                    client = Client(
                        code=code_clean,
                        trade_name=effective_trade,
                        name=effective_name,
                        owner_name=owner,
                        department=dept,
                        municipality=muni,
                        address=address,
                        ruc=ruc,
                        phone=phone,
                        salesperson=salesperson,
                        registration_number=matricula,
                        credit_limit=credit_limit,
                        term_code=term_code,
                        credit_days=credit_days,
                        transport=transport,
                        payment_condition=cond,
                        is_active=True
                    )
                    db.session.add(client)
                    report['clients_created'] += 1
                    if not full_clean and trade_clean:
                        report['clients_recovered'] += 1
                else:
                    client.trade_name = effective_trade
                    client.name = effective_name
                    client.owner_name = owner
                    client.department = dept
                    client.municipality = muni
                    client.address = address
                    client.ruc = ruc
                    client.phone = phone
                    client.salesperson = salesperson
                    if credit_limit > 0 and not client.credit_limit:
                        client.credit_limit = credit_limit
                    client.term_code = term_code
                    client.credit_days = credit_days
                    client.transport = transport
                    client.payment_condition = cond
                    report['clients_updated'] += 1

            db.session.flush()

        # Build lookup caches for movements
        prod_map = {p.code: p for p in Product.query.all()}
        client_map = {c.code: c for c in Client.query.all()}
        client_name_map = {}
        for c in client_map.values():
            if c.name:
                client_name_map[c.name.upper()] = c
            if c.trade_name:
                client_name_map[c.trade_name.upper()] = c

        existing_movs = {
            m.code: m for m in InventoryMovement.query.filter(InventoryMovement.code.like('MOV-HIST-%')).all()
        }

        # 4. Import / Reconcile Movements from 'REGISTRO Entradas - Salidas'
        if 'REGISTRO Entradas - Salidas' in wb.sheetnames:
            ws_m = wb['REGISTRO Entradas - Salidas']
            for r in range(8, ws_m.max_row + 1):
                raw_date = ws_m.cell(r, 2).value
                prod_code = ws_m.cell(r, 3).value
                origen = ws_m.cell(r, 7).value
                raw_qty = ws_m.cell(r, 10).value
                if not prod_code or not origen or raw_qty is None:
                    continue

                prod_code_clean = str(prod_code).strip()
                if prod_code_clean not in prod_map:
                    continue
                product = prod_map[prod_code_clean]

                origen_clean = str(origen).strip()
                try:
                    qty = abs(float(raw_qty))
                except (ValueError, TypeError):
                    continue

                if isinstance(raw_date, datetime):
                    mov_date = raw_date
                elif isinstance(raw_date, date):
                    mov_date = datetime.combine(raw_date, datetime.min.time())
                else:
                    mov_date = datetime.utcnow()

                try: unit_price = float(ws_m.cell(r, 11).value or 0.0)
                except (ValueError, TypeError): unit_price = 0.0

                try: unit_cost = float(ws_m.cell(r, 17).value or 0.0)
                except (ValueError, TypeError): unit_cost = 0.0

                # Update product purchase_price if it was 0.0 and we have historical unit_cost
                if unit_cost > 0 and (product.purchase_price or 0.0) == 0.0:
                    product.purchase_price = round(unit_cost, 2)

                client_prov_code = str(ws_m.cell(r, 12).value or '').strip()
                client_prov_name = str(ws_m.cell(r, 13).value or '').strip()
                invoice_num = str(ws_m.cell(r, 14).value or '').strip()
                tax_applied = str(ws_m.cell(r, 15).value or '').strip() or None

                try: dscto_pct = float(ws_m.cell(r, 18).value or 0.0)
                except (ValueError, TypeError): dscto_pct = 0.0

                try: dscto_amt = float(ws_m.cell(r, 19).value or 0.0)
                except (ValueError, TypeError): dscto_amt = 0.0

                try: venta_real = float(ws_m.cell(r, 20).value or 0.0)
                except (ValueError, TypeError): venta_real = 0.0

                raw_status = ws_m.cell(r, 22).value
                pay_cond = str(raw_status).strip() if raw_status and str(raw_status).strip() != '0' else None

                raw_vence = ws_m.cell(r, 23).value
                due_dt = None
                if isinstance(raw_vence, datetime):
                    due_dt = raw_vence.date()
                elif isinstance(raw_vence, date):
                    due_dt = raw_vence

                # Resolve supplier or client accurately
                if origen_clean == 'Compra':
                    op_type = 'Compra'
                    if 'campo' in client_prov_code.lower() or 'campo' in client_prov_name.lower():
                        supp_id = campovet.id
                        report['campovet_movements'] += 1
                    else:
                        supp_id = novavet.id
                        report['novavet_movements'] += 1
                    cli_id = None
                elif origen_clean == 'Venta':
                    op_type = 'Venta'
                    cli = client_map.get(client_prov_code) or client_name_map.get(client_prov_name.upper()) or client_name_map.get(client_prov_code.upper())
                    cli_id = cli.id if cli else None
                    supp_id = None
                elif origen_clean == 'Regalias':
                    op_type = 'Regalias'
                    cli = client_map.get(client_prov_code) or client_name_map.get(client_prov_name.upper())
                    cli_id = cli.id if cli else None
                    supp_id = novavet.id if not cli else None
                else:
                    op_type = 'Ajuste_Entrada'
                    cli_id = None
                    supp_id = None

                mov_code = f"MOV-HIST-{r:05d}"
                total_val = round(venta_real if venta_real > 0 else (qty * (unit_price if unit_price > 0 else unit_cost)), 2)

                if mov_code in existing_movs:
                    # Enrich existing movement without duplicating!
                    existing_m = existing_movs[mov_code]
                    existing_m.supplier_id = supp_id
                    existing_m.client_id = cli_id
                    existing_m.tax_applied = tax_applied
                    existing_m.discount_percent = dscto_pct
                    existing_m.discount_amount = dscto_amt
                    existing_m.payment_condition = pay_cond
                    existing_m.due_date = due_dt
                    existing_m.total_value = total_val
                    report['duplicates_skipped'] += 1
                    report['movements_enriched'] += 1
                else:
                    mov = InventoryMovement(
                        code=mov_code,
                        product_id=product.id,
                        operation_type=op_type,
                        quantity=qty,
                        previous_stock=0.0,
                        new_stock=0.0,
                        unit_price=unit_price,
                        unit_cost=unit_cost,
                        total_value=total_val,
                        tax_applied=tax_applied,
                        discount_percent=dscto_pct,
                        discount_amount=dscto_amt,
                        payment_condition=pay_cond,
                        due_date=due_dt,
                        client_id=cli_id,
                        supplier_id=supp_id,
                        invoice_number=invoice_num if invoice_num and invoice_num != 'None' else None,
                        salesperson=None,
                        warehouse=product.warehouse or 'Principal',
                        reason=f"Importado de historial Excel ({origen_clean})",
                        notes=f"Ref: {client_prov_name or client_prov_code}",
                        user_id=user_id,
                        created_at=mov_date
                    )
                    db.session.add(mov)
                    report['movements_imported'] += 1

        audit = AuditLog(
            user_id=user_id,
            action='IMPORT_MASTER_EXCEL',
            entity_type='Database',
            details=(
                f"Importación/Conciliación Excel: Proveedores +{report['suppliers_created']}, "
                f"Productos +{report['products_created']} (act: {report['products_updated']}), "
                f"Clientes +{report['clients_created']} (recuperados: {report['clients_recovered']}, act: {report['clients_updated']}), "
                f"Movimientos nuevos: {report['movements_imported']}, enriquecidos sin duplicar: {report['movements_enriched']} "
                f"(Novavet: {report['novavet_movements']}, CampoVet: {report['campovet_movements']})."
            )
        )
        db.session.add(audit)
        db.session.commit()

        return report

    @staticmethod
    def export_data_to_excel(title, headers, rows, filename_prefix="Reporte_CityPet"):
        """
        Exports tabular data to a professionally styled Excel spreadsheet.
        """
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = title[:30]

        header_fill = PatternFill(start_color="0F5B9E", end_color="0F5B9E", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=15, bold=True, color="0F5B9E")
        subtitle_font = Font(name="Calibri", size=10, italic=True, color="555555")
        border_thin = Border(
            left=Side(style='thin', color='DDDDDD'),
            right=Side(style='thin', color='DDDDDD'),
            top=Side(style='thin', color='DDDDDD'),
            bottom=Side(style='thin', color='DDDDDD')
        )

        ws.cell(1, 1).value = f"CITYPET PHARMA — {title.upper()}"
        ws.cell(1, 1).font = title_font
        ws.cell(2, 1).value = f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Sistema CityPet"
        ws.cell(2, 1).font = subtitle_font

        start_row = 4
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(start_row, col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        curr_row = start_row + 1
        for row in rows:
            for col_idx, val in enumerate(row, start=1):
                cell = ws.cell(curr_row, col_idx, value=val)
                cell.border = border_thin
                if isinstance(val, (int, float)):
                    cell.alignment = Alignment(horizontal="right")
                else:
                    cell.alignment = Alignment(horizontal="left")
            curr_row += 1

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output
