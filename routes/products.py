import os
from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from extensions import db
from models import Product, Supplier, InventoryMovement, AuditLog
from services.inventory_service import InventoryService
from services.storage_service import StorageService, StorageValidationError
from routes.auth import admin_required

products_bp = Blueprint('products', __name__, url_prefix='/products')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config.get('ALLOWED_IMAGE_EXTENSIONS', {'png', 'jpg', 'jpeg', 'webp'})

@products_bp.route('/')
@login_required
def index():
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    status_filter = request.args.get('status', '').strip()
    supplier_id = request.args.get('supplier_id', type=int)

    query = Product.query

    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f"%{search}%"),
                Product.code.ilike(f"%{search}%"),
                Product.barcode.ilike(f"%{search}%")
            )
        )
    if category:
        query = query.filter_by(category=category)
    if supplier_id:
        query = query.filter_by(supplier_id=supplier_id)

    products = query.order_by(Product.code.asc()).all()

    # In-memory filter for computed properties if requested
    if status_filter:
        products = [p for p in products if p.status == status_filter]

    # Categories list for filter dropdown
    categories = [c[0] for c in db.session.query(Product.category).distinct().filter(Product.category != None).all() if c[0]]
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name.asc()).all()

    return render_template(
        'products/index.html',
        products=products,
        categories=categories,
        suppliers=suppliers,
        search=search,
        selected_category=category,
        selected_status=status_filter,
        selected_supplier=supplier_id
    )

@products_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create():
    name = request.form.get('name', '').strip()
    if not name:
        flash("El nombre del producto es obligatorio.", "danger")
        return redirect(url_for('products.index'))

    # Auto generate code if empty
    code = request.form.get('code', '').strip()
    if not code:
        last_prod = Product.query.order_by(Product.id.desc()).first()
        next_num = (last_prod.id + 1) if last_prod else 1
        code = f"CP{next_num:06d}"

    if Product.query.filter_by(code=code).first():
        flash(f"Ya existe un producto con el código '{code}'.", "danger")
        return redirect(url_for('products.index'))

    category = request.form.get('category', 'General').strip()
    warehouse = request.form.get('warehouse', 'Principal').strip()
    unit = request.form.get('unit', 'Unid').strip()
    barcode = request.form.get('barcode', '').strip() or None
    description = request.form.get('description', '').strip() or None
    supplier_id = request.form.get('supplier_id', type=int)

    try: purchase_price = max(0.0, float(request.form.get('purchase_price') or 0.0))
    except ValueError: purchase_price = 0.0

    try: sale_price = max(0.0, float(request.form.get('sale_price') or 0.0))
    except ValueError: sale_price = 0.0

    try: min_stock = max(0.0, float(request.form.get('min_stock') or 5.0))
    except ValueError: min_stock = 5.0

    try: initial_stock = max(0.0, float(request.form.get('initial_stock') or 0.0))
    except ValueError: initial_stock = 0.0

    # Image upload (validated & persisted via StorageService: Supabase Storage or local)
    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            try:
                image_url = StorageService.save_product_image(file, code)
            except (StorageValidationError, RuntimeError) as exc:
                flash(str(exc), "danger")
                return redirect(url_for('products.index'))

    product = Product(
        code=code,
        name=name,
        category=category,
        warehouse=warehouse,
        unit=unit,
        barcode=barcode,
        description=description,
        image_url=image_url,
        purchase_price=purchase_price,
        sale_price=sale_price,
        current_stock=0.0, # Initial stock will be added via transaction
        min_stock=min_stock,
        physical_stock=initial_stock,
        supplier_id=supplier_id,
        is_active=True
    )
    db.session.add(product)
    db.session.flush()

    if initial_stock > 0:
        InventoryService.record_movement(
            product_id=product.id,
            operation_type='Inventario_Inicial',
            quantity=initial_stock,
            user_id=current_user.id,
            reason="Inventario Inicial al crear producto",
            unit_cost=purchase_price,
            unit_price=sale_price
        )

    audit = AuditLog(
        user_id=current_user.id,
        action='CREATE_PRODUCT',
        entity_type='Product',
        entity_id=str(product.id),
        details=f"Producto creado: {product.code} - {product.name}"
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Producto '{product.name}' registrado exitosamente con código {product.code}.", "success")
    return redirect(url_for('products.index'))

@products_bp.route('/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit(id):
    product = Product.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    if not name:
        flash("El nombre no puede estar vacío.", "danger")
        return redirect(url_for('products.index'))

    product.name = name
    product.category = request.form.get('category', product.category).strip()
    product.warehouse = request.form.get('warehouse', product.warehouse).strip()
    product.unit = request.form.get('unit', product.unit).strip()
    product.barcode = request.form.get('barcode', '').strip() or None
    product.description = request.form.get('description', '').strip() or None
    product.supplier_id = request.form.get('supplier_id', type=int)

    try: product.purchase_price = max(0.0, float(request.form.get('purchase_price') or product.purchase_price))
    except ValueError: pass

    try: product.sale_price = max(0.0, float(request.form.get('sale_price') or product.sale_price))
    except ValueError: pass

    try: product.min_stock = max(0.0, float(request.form.get('min_stock') or product.min_stock))
    except ValueError: pass

    try: product.physical_stock = max(0.0, float(request.form.get('physical_stock') or product.physical_stock))
    except ValueError: pass

    # Optional image upload (validated & persisted via StorageService)
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            try:
                product.image_url = StorageService.save_product_image(file, product.code)
            except (StorageValidationError, RuntimeError) as exc:
                flash(str(exc), "danger")
                return redirect(url_for('products.index'))

    audit = AuditLog(
        user_id=current_user.id,
        action='UPDATE_PRODUCT',
        entity_type='Product',
        entity_id=str(product.id),
        details=f"Producto actualizado: {product.code} - {product.name}"
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Producto '{product.name}' actualizado correctamente.", "success")
    return redirect(url_for('products.index'))

@products_bp.route('/<int:id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_status(id):
    product = Product.query.get_or_404(id)
    product.is_active = not product.is_active
    action_str = "activado" if product.is_active else "desactivado (archivado)"
    
    audit = AuditLog(
        user_id=current_user.id,
        action='TOGGLE_PRODUCT_STATUS',
        entity_type='Product',
        entity_id=str(product.id),
        details=f"Producto {product.code} {action_str}"
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Producto '{product.name}' ha sido {action_str}.", "info")
    return redirect(url_for('products.index'))

@products_bp.route('/<int:id>/history')
@login_required
def history(id):
    product = Product.query.get_or_404(id)
    movements = InventoryMovement.query.filter_by(product_id=id).order_by(InventoryMovement.created_at.desc()).all()
    return render_template('products/history.html', product=product, movements=movements)

@products_bp.route('/api/search')
@login_required
def api_search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    products = Product.query.filter(
        Product.is_active == True,
        db.or_(
            Product.name.ilike(f"%{query}%"),
            Product.code.ilike(f"%{query}%"),
            Product.barcode == query
        )
    ).limit(20).all()

    return jsonify([p.to_dict() for p in products])
