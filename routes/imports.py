import os
import openpyxl
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from extensions import db
from models import Product, Client, Supplier, AuditLog
from services.excel_service import ExcelService
from services.storage_service import StorageService, StorageValidationError
from routes.auth import admin_required

imports_bp = Blueprint('imports', __name__, url_prefix='/imports')

@imports_bp.route('/')
@login_required
@admin_required
def index():
    master_file = os.path.join(current_app.root_path, 'INVENTARIO NUEVO.xlsx')
    master_file_exists = os.path.exists(master_file)
    master_file_size = f"{os.path.getsize(master_file)/1024:.1f} KB" if master_file_exists else "0 KB"

    master_preview = None
    if master_file_exists:
        try:
            master_preview = ExcelService.preview_citypet_master_excel(master_file)
        except Exception:
            master_preview = None

    return render_template(
        'imports/index.html',
        master_file_exists=master_file_exists,
        master_file_size=master_file_size,
        master_preview=master_preview
    )

@imports_bp.route('/master-preview', methods=['GET'])
@login_required
@admin_required
def master_preview():
    master_file = os.path.join(current_app.root_path, 'INVENTARIO NUEVO.xlsx')
    if not os.path.exists(master_file):
        return jsonify({'success': False, 'error': "Archivo 'INVENTARIO NUEVO.xlsx' no encontrado."}), 404
    try:
        preview = ExcelService.preview_citypet_master_excel(master_file)
        return jsonify({'success': True, 'preview': preview})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@imports_bp.route('/master-excel', methods=['POST'])
@login_required
@admin_required
def import_master():
    master_file = os.path.join(current_app.root_path, 'INVENTARIO NUEVO.xlsx')
    if not os.path.exists(master_file):
        flash("El archivo 'INVENTARIO NUEVO.xlsx' no se encontró en la raíz del proyecto.", "danger")
        return redirect(url_for('imports.index'))

    try:
        report = ExcelService.import_citypet_master_excel(master_file, current_user.id)
        flash(
            f"¡Importación y conciliación maestra completada con éxito! "
            f"Productos creados: {report['products_created']} (actualizados: {report['products_updated']}), "
            f"Clientes creados: {report['clients_created']} (incluyendo {report.get('omitted_clients_recovered', 0)} con Solo Razón Social; actualizados: {report['clients_updated']}), "
            f"Proveedores creados: {report.get('suppliers_created', 0)} (actualizados: {report.get('suppliers_updated', 0)}), "
            f"Movimientos históricos nuevos: {report['movements_imported']} (enriquecidos sin duplicar: {report.get('movements_updated', 0)}).",
            "success"
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Error procesando la importación maestra: {str(e)}", "danger")

    return redirect(url_for('imports.index'))

@imports_bp.route('/preview', methods=['POST'])
@login_required
@admin_required
def preview_file():
    if 'excel_file' not in request.files:
        flash("No se seleccionó ningún archivo.", "warning")
        return redirect(url_for('imports.index'))

    file = request.files['excel_file']
    if not file or not file.filename:
        flash("Archivo no válido.", "warning")
        return redirect(url_for('imports.index'))

    try:
        temp_filename, temp_path = StorageService.validate_and_save_temp_excel(file, current_user.id)
    except StorageValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for('imports.index'))

    try:
        with open(temp_path, 'rb') as f:
            sheets_data = ExcelService.parse_sheet_preview(f)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        flash(f"Error al leer el archivo Excel: {str(e)}", "danger")
        return redirect(url_for('imports.index'))

    return render_template(
        'imports/preview.html',
        temp_file=temp_filename,
        sheets=sheets_data
    )

@imports_bp.route('/execute', methods=['POST'])
@login_required
@admin_required
def execute_import():
    temp_filename = secure_filename(request.form.get('temp_file') or '')
    if not temp_filename or not temp_filename.startswith('temp_import_'):
        flash("Archivo temporal de importación inválido.", "danger")
        return redirect(url_for('imports.index'))
    target_entity = request.form.get('target_entity') # 'products', 'clients', 'suppliers'
    sheet_name = request.form.get('sheet_name')
    header_row = int(request.form.get('header_row', 1))

    temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], temp_filename)
    if not os.path.exists(temp_path):
        flash("La sesión de importación ha expirado o el archivo no existe.", "danger")
        return redirect(url_for('imports.index'))

    wb = openpyxl.load_workbook(temp_path, data_only=True)
    if sheet_name not in wb.sheetnames:
        flash("La hoja seleccionada no existe en el archivo.", "danger")
        return redirect(url_for('imports.index'))

    ws = wb[sheet_name]
    created = 0
    updated = 0

    try:
        if target_entity == 'products':
            col_code = int(request.form.get('col_code', -1))
            col_name = int(request.form.get('col_name', -1))
            col_cat = int(request.form.get('col_category', -1))
            col_price = int(request.form.get('col_sale_price', -1))
            col_cost = int(request.form.get('col_purchase_price', -1))
            col_stock = int(request.form.get('col_stock', -1))

            for r in range(header_row + 1, ws.max_row + 1):
                name_val = ws.cell(r, col_name).value if col_name > 0 else None
                if not name_val:
                    continue

                code_val = str(ws.cell(r, col_code).value or f"CP-IMP-{r}").strip() if col_code > 0 else f"CP-IMP-{r}"
                cat_val = str(ws.cell(r, col_cat).value or 'General').strip() if col_cat > 0 else 'General'
                
                try: price_val = float(ws.cell(r, col_price).value or 0.0) if col_price > 0 else 0.0
                except (ValueError, TypeError): price_val = 0.0

                try: cost_val = float(ws.cell(r, col_cost).value or 0.0) if col_cost > 0 else 0.0
                except (ValueError, TypeError): cost_val = 0.0

                try: stock_val = float(ws.cell(r, col_stock).value or 0.0) if col_stock > 0 else 0.0
                except (ValueError, TypeError): stock_val = 0.0

                p = Product.query.filter_by(code=code_val).first()
                if not p:
                    p = Product(
                        code=code_val,
                        name=str(name_val).strip(),
                        category=cat_val,
                        sale_price=price_val,
                        purchase_price=cost_val,
                        current_stock=max(0.0, stock_val),
                        physical_stock=max(0.0, stock_val),
                        is_active=True
                    )
                    db.session.add(p)
                    created += 1
                else:
                    p.name = str(name_val).strip()
                    p.category = cat_val
                    p.sale_price = price_val
                    p.purchase_price = cost_val
                    updated += 1

            db.session.commit()

        elif target_entity == 'clients':
            col_code = int(request.form.get('col_code', -1))
            col_name = int(request.form.get('col_name', -1))
            col_phone = int(request.form.get('col_phone', -1))
            col_ruc = int(request.form.get('col_ruc', -1))
            col_addr = int(request.form.get('col_address', -1))

            for r in range(header_row + 1, ws.max_row + 1):
                name_val = ws.cell(r, col_name).value if col_name > 0 else None
                if not name_val:
                    continue

                code_val = str(ws.cell(r, col_code).value or f"CLI-IMP-{r}").strip() if col_code > 0 else f"CLI-IMP-{r}"
                phone_val = str(ws.cell(r, col_phone).value or '').strip() if col_phone > 0 else ''
                ruc_val = str(ws.cell(r, col_ruc).value or '').strip() if col_ruc > 0 else ''
                addr_val = str(ws.cell(r, col_addr).value or '').strip() if col_addr > 0 else ''

                c = Client.query.filter_by(code=code_val).first()
                if not c:
                    c = Client(
                        code=code_val,
                        name=str(name_val).strip(),
                        phone=phone_val,
                        ruc=ruc_val,
                        address=addr_val,
                        is_active=True
                    )
                    db.session.add(c)
                    created += 1
                else:
                    c.name = str(name_val).strip()
                    c.phone = phone_val
                    c.ruc = ruc_val
                    c.address = addr_val
                    updated += 1

            db.session.commit()

        if os.path.exists(temp_path):
            os.remove(temp_path)

        flash(f"Importación completada: {created} registros creados, {updated} actualizados.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error durante la importación: {str(e)}", "danger")

    return redirect(url_for('imports.index'))
