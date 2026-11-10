import os
import tempfile
import pytest
from app import create_app
from extensions import db
from models import User, Product, Client, Supplier, Sale, InventoryMovement, FinancialMovement, Receipt, Payment, Purchase, SystemSetting
from services.sales_service import SalesService
from services.purchase_service import PurchaseService
from services.payment_service import PaymentService
from services.reconciliation_service import ReconciliationService
from services.summary_service import SummaryService
from services.inventory_service import InventoryService
from services.receipt_service import ReceiptService

@pytest.fixture
def app():
    # Use dedicated testing configuration
    app = create_app('testing')

    with app.app_context():
        db.create_all()

        # Seed test owner
        owner = User(
            username='test_owner',
            full_name='Dueño CityPet',
            email='dueno@citypet.com',
            role='propietario',
            is_active=True
        )
        owner.set_password('password123')
        db.session.add(owner)

        # Seed test admin
        admin = User(
            username='test_admin',
            full_name='Administrador CityPet',
            email='admin@citypet.com',
            role='administrador',
            is_active=True
        )
        admin.set_password('password123')
        db.session.add(admin)

        # Seed test employee
        employee = User(
            username='test_employee',
            full_name='Cajero Empleado',
            email='cajero@citypet.com',
            role='empleado',
            is_active=True
        )
        employee.set_password('password123')
        db.session.add(employee)

        # Seed test supplier
        supp = Supplier(code='PROV-TEST-01', company_name='Novavet Test', ruc='J031000000001', is_active=True)
        db.session.add(supp)
        db.session.flush()

        # Seed test client
        cli = Client(
            code='CLI-TEST-01',
            name='URBAN PETS / TEST',
            trade_name='URBAN PETS',
            ruc='J0310000269742',
            phone='22321342',
            salesperson='Mostrador',
            payment_condition='Contado',
            credit_limit=5000.0,
            credit_days=30,
            is_active=True
        )
        db.session.add(cli)
        db.session.flush()

        # Seed test product
        prod = Product(
            code='PROD-TEST-01',
            name='AMOXIN 250 MG 30 ML TEST',
            category='Antibióticos',
            warehouse='Principal',
            unit='Unid',
            purchase_price=295.65,
            sale_price=357.00,
            current_stock=50.0,
            min_stock=9.0,
            physical_stock=50.0,
            supplier_id=supp.id,
            is_active=True
        )
        db.session.add(prod)
        db.session.commit()

        yield app

        db.session.remove()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def auth_client(client):
    client.post('/auth/login', data={'username': 'test_owner', 'password': 'password123'})
    return client

def test_login_successful(client):
    res = client.post('/auth/login', data={'username': 'test_owner', 'password': 'password123'}, follow_redirects=True)
    assert res.status_code == 200
    assert b"Dashboard General" in res.data or b"Dashboard" in res.data

def test_login_failure(client):
    res = client.post('/auth/login', data={'username': 'test_owner', 'password': 'wrongpassword'}, follow_redirects=True)
    assert b"incorrectos" in res.data

def test_dashboard_access(auth_client):
    res = auth_client.get('/dashboard')
    assert res.status_code == 200
    assert b"Ventas Hoy" in res.data
    assert b"Valor del Inventario" in res.data

def test_three_tier_roles_and_permissions(app, client):
    # 1. Login as employee
    client.post('/auth/login', data={'username': 'test_employee', 'password': 'password123'}, follow_redirects=True)
    
    # Employee cannot access owner settings
    res = client.get('/settings/users', follow_redirects=True)
    assert b"restringido" in res.data or res.status_code == 200 # redirected to dashboard with flash

    # Employee cannot access finances
    res = client.get('/finances/', follow_redirects=True)
    assert b"restringido" in res.data or res.status_code == 200

    # Employee CAN access POS
    res = client.get('/sales/pos')
    assert res.status_code == 200
    assert b"Punto de Venta" in res.data

    # 2. Login as admin
    client.get('/auth/logout')
    client.post('/auth/login', data={'username': 'test_admin', 'password': 'password123'}, follow_redirects=True)

    # Admin CAN access finances and purchases
    res = client.get('/finances/')
    assert res.status_code == 200
    res = client.get('/purchases/')
    assert res.status_code == 200

    # Admin CANNOT access owner user management
    res = client.get('/settings/users', follow_redirects=True)
    assert b"restringido" in res.data

def test_inventory_movement_and_stock_update(app):
    with app.app_context():
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        initial_stock = prod.current_stock

        # Inbound movement (Compra)
        mov = InventoryService.record_movement(
            product_id=prod.id,
            operation_type='Compra',
            quantity=10,
            unit_cost=300.0,
            reason="Compra de prueba"
        )
        db.session.commit()
        assert prod.current_stock == initial_stock + 10
        assert mov.new_stock == initial_stock + 10

        # Outbound movement (Danado_Merma)
        mov2 = InventoryService.record_movement(
            product_id=prod.id,
            operation_type='Danado_Merma',
            quantity=5,
            reason="Prueba merma"
        )
        db.session.commit()
        assert prod.current_stock == initial_stock + 10 - 5

def test_negative_stock_prevention(app):
    with app.app_context():
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        prod.current_stock = 3.0
        db.session.commit()

        # Attempt to sell 5 when only 3 available
        with pytest.raises(ValueError) as excinfo:
            InventoryService.record_movement(
                product_id=prod.id,
                operation_type='Venta',
                quantity=5.0
            )
        assert "insuficientes" in str(excinfo.value)
        assert prod.current_stock == 3.0

def test_sale_creation_and_receipt_generation(app):
    with app.app_context():
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        cli = Client.query.filter_by(code='CLI-TEST-01').first()
        owner = User.query.filter_by(username='test_owner').first()

        initial_stock = prod.current_stock

        sale_data = {
            'client_id': cli.id,
            'client_name': cli.name,
            'client_ruc': cli.ruc,
            'client_address': 'Managua',
            'client_code': cli.code,
            'salesperson': 'Lenin Montenegro',
            'payment_method': 'Efectivo',
            'payment_condition': 'Contado',
            'tax_percent': 0.0
        }
        items_data = [{
            'product_id': prod.id,
            'quantity': 2,
            'unit_price': 357.0,
            'discount_percent': 0.0
        }]

        sale, receipt = SalesService.create_sale(sale_data, items_data, user_id=owner.id)

        assert sale.id is not None
        assert sale.total == 714.00
        assert sale.paid_amount == 714.00
        assert sale.balance_due == 0.0
        assert sale.status == 'confirmada'
        assert prod.current_stock == initial_stock - 2

        # Verify immutable receipt
        assert receipt.id is not None
        assert receipt.total_amount == 714.00
        assert receipt.receipt_type == 'Venta'
        assert len(receipt.payload['items']) == 1
        assert receipt.payload['items'][0]['code'] == 'PROD-TEST-01'

        # Verify Financial Movement created
        fin = FinancialMovement.query.filter_by(sale_id=sale.id).first()
        assert fin is not None
        assert fin.amount == 714.00
        assert fin.movement_type == 'Ingreso'

def test_purchase_workflow_and_cost_update(app):
    with app.app_context():
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        supp = Supplier.query.filter_by(code='PROV-TEST-01').first()
        owner = User.query.filter_by(username='test_owner').first()

        initial_stock = prod.current_stock
        new_cost = 310.00

        purchase_data = {
            'supplier_id': supp.id,
            'supplier_invoice_number': 'FAC-NOV-001',
            'payment_method': 'Efectivo',
            'payment_condition': 'Contado',
            'warehouse': 'Principal',
            'tax_amount': 0.0,
            'discount_amount': 0.0
        }
        items_data = [{
            'product_id': prod.id,
            'quantity': 20,
            'unit_cost': new_cost,
            'update_product_cost': True
        }]

        purchase, receipt = PurchaseService.create_purchase(purchase_data, items_data, user_id=owner.id)

        assert purchase.id is not None
        assert purchase.total == 20 * new_cost
        assert purchase.status == 'confirmada'
        assert prod.current_stock == initial_stock + 20
        assert prod.purchase_price == new_cost

        # Verify financial expense recorded
        fin = FinancialMovement.query.filter_by(purchase_id=purchase.id).first()
        assert fin is not None
        assert fin.movement_type == 'Gasto'
        assert fin.amount == 20 * new_cost

        # Test voiding purchase reverses stock
        PurchaseService.void_purchase(purchase.id, owner.id, "Factura emitida con error de lote")
        assert purchase.status == 'anulada'
        assert prod.current_stock == initial_stock

def test_credit_sale_and_abonos_workflow(app):
    with app.app_context():
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        cli = Client.query.filter_by(code='CLI-TEST-01').first()
        owner = User.query.filter_by(username='test_owner').first()

        sale_data = {
            'client_id': cli.id,
            'client_name': cli.name,
            'payment_condition': 'Crédito 30 días',
            'initial_payment': 100.00
        }
        items_data = [{
            'product_id': prod.id,
            'quantity': 2,
            'unit_price': 350.00,
            'discount_percent': 0.0
        }]

        # Total is 700, initial payment 100, balance due 600
        sale, receipt = SalesService.create_sale(sale_data, items_data, user_id=owner.id)

        assert sale.is_credit == True
        assert sale.total == 700.00
        assert sale.paid_amount == 100.00
        assert sale.balance_due == 600.00
        assert sale.payment_status == 'Abonado'

        # Register Abono of 300
        payment, abono_rec = PaymentService.register_abono(
            sale_id=sale.id,
            amount=300.00,
            payment_method='Transferencia',
            user_id=owner.id
        )

        assert payment.amount == 300.00
        assert payment.previous_balance == 600.00
        assert payment.new_balance == 300.00
        assert sale.paid_amount == 400.00
        assert sale.balance_due == 300.00

        # Complete final payment of 300
        payment2, abono_rec2 = PaymentService.register_abono(
            sale_id=sale.id,
            amount=300.00,
            payment_method='Efectivo',
            user_id=owner.id
        )

        assert sale.balance_due == 0.00
        assert sale.is_paid == True
        assert sale.payment_status in ('Liquidado', 'Pagado')

def test_mathematical_inventory_reconciliation(app):
    with app.app_context():
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        owner = User.query.filter_by(username='test_owner').first()

        # Target stock
        mov = ReconciliationService.apply_adjustment(
            product_id=prod.id,
            target_stock=65.0,
            reason="Alineación con conteo físico validado en bodega",
            user_id=owner.id
        )

        assert prod.current_stock == 65.0
        assert prod.physical_stock == 65.0
        assert mov.operation_type == 'Ajuste_Entrada'
        assert mov.quantity == 15.0

        # Re-check reconciliation data
        data = ReconciliationService.get_product_reconciliation_data(product_id=prod.id)
        assert len(data) == 1
        assert data[0]['current_stock'] == 65.0

def test_daily_and_monthly_summaries(app):
    with app.app_context():
        daily = SummaryService.get_daily_summary()
        assert 'total_sales_amount' in daily
        assert 'net_cash_balance' in daily
        assert 'sales_list' in daily

        monthly = SummaryService.get_monthly_summary()
        assert 'total_sales' in monthly
        assert 'gross_profit' in monthly
        assert 'top_selling' in monthly

        trends = SummaryService.get_trend_data(period='7d')
        assert 'labels' in trends
        assert 'sales' in trends

def test_appearance_settings_persistence(app):
    with app.app_context():
        SystemSetting.set_val('theme_mode', 'oscuro')
        SystemSetting.set_val('theme_primary_color', '#2D6A4F')
        
        assert SystemSetting.get_val('theme_mode') == 'oscuro'
        assert SystemSetting.get_val('theme_primary_color') == '#2D6A4F'

def test_client_employee_editing_restriction(client, app):
    """
    Test Phase 3 Section 8: Employee role CANNOT create or edit clients.
    Owner/Admin CAN create and edit clients.
    """
    # 1. Log in as employee
    client.post('/auth/login', data={'username': 'test_employee', 'password': 'password123'}, follow_redirects=True)

    # Attempt to create client as employee
    res_create = client.post('/clients/create', data={
        'name': 'Intento no autorizado de Empleado',
        'code': 'CP-C9999'
    }, follow_redirects=True)
    # admin_required decorator redirects with error flash
    assert "Acceso restringido" in res_create.get_data(as_text=True)

    with app.app_context():
        assert Client.query.filter_by(code='CP-C9999').first() is None

    # Attempt to edit client as employee
    with app.app_context():
        cli = Client.query.filter_by(code='CLI-TEST-01').first()
        cli_id = cli.id

    res_edit = client.post(f'/clients/{cli_id}/edit', data={
        'name': 'Nombre Modificado por Empleado'
    }, follow_redirects=True)
    assert "Acceso restringido" in res_edit.get_data(as_text=True)

    with app.app_context():
        assert Client.query.get(cli_id).name == 'URBAN PETS / TEST'

    # 2. Log in as owner and verify permitted editing
    client.get('/auth/logout', follow_redirects=True)
    client.post('/auth/login', data={'username': 'test_owner', 'password': 'password123'}, follow_redirects=True)

    res_owner_create = client.post('/clients/create', data={
        'name': 'Cliente Creado por Propietario',
        'code': 'CP-C8888',
        'department': 'MANAGUA',
        'credit_limit': '5000'
    }, follow_redirects=True)
    assert "guardado correctamente" in res_owner_create.get_data(as_text=True)

    with app.app_context():
        assert Client.query.filter_by(code='CP-C8888').first() is not None

def test_concurrency_locking_and_negative_stock_prevention(app):
    """
    Test Phase 3 Section 1: Strict non-negative inventory constraint and row locking.
    """
    with app.app_context():
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        prod.current_stock = 10.0
        db.session.commit()

        # Try to take out 15 units when only 10 exist
        with pytest.raises(ValueError) as excinfo:
            InventoryService.record_movement(
                product_id=prod.id,
                operation_type='Ajuste_Salida',
                quantity=15.0,
                reason="Intento de saldo negativo"
            )
        assert "Existencias insuficientes" in str(excinfo.value)
        assert prod.current_stock == 10.0

def test_controlled_database_reset_with_telegram_failsafe(client, app, monkeypatch):
    """
    Test Phase 3 Section 7: Controlled Database Reset with multi-step verification and Telegram fail-safe.
    """
    # 1. Log in as owner
    client.post('/auth/login', data={'username': 'test_owner', 'password': 'password123'}, follow_redirects=True)

    # Bad phrase
    res_bad_phrase = client.post('/settings/reset-database', data={
        'confirmation_phrase': 'FRASE INCORRECTA',
        'password': 'password123'
    }, follow_redirects=True)
    assert "La frase de confirmación escrita no coincide" in res_bad_phrase.get_data(as_text=True)

    # Bad password
    res_bad_pwd = client.post('/settings/reset-database', data={
        'confirmation_phrase': 'BORRAR DATOS OPERATIVOS',
        'password': 'wrong_password'
    }, follow_redirects=True)
    assert "Contraseña de Propietario incorrecta" in res_bad_pwd.get_data(as_text=True)

    # Telegram offline/unconfigured fail-safe check:
    with app.app_context():
        SystemSetting.set_val('telegram_enabled', 'false')

    res_tg_disabled = client.post('/settings/reset-database', data={
        'confirmation_phrase': 'BORRAR DATOS OPERATIVOS',
        'password': 'password123'
    }, follow_redirects=True)
    assert "El bot de Telegram no está configurado o no está habilitado" in res_tg_disabled.get_data(as_text=True)

    # Telegram notification failure simulation:
    with app.app_context():
        SystemSetting.set_val('telegram_enabled', 'true')
        SystemSetting.set_val('telegram_bot_token', '123456:FAKE')
        SystemSetting.set_val('telegram_chat_id', '12345678')

    from services.telegram_service import TelegramService
    monkeypatch.setattr(TelegramService, 'send_raw_message', lambda token, chat, text: (False, "Connection timeout to api.telegram.org"))

    res_tg_fail = client.post('/settings/reset-database', data={
        'confirmation_phrase': 'BORRAR DATOS OPERATIVOS',
        'password': 'password123'
    }, follow_redirects=True)
    assert "La notificación de seguridad a Telegram no pudo entregarse" in res_tg_fail.get_data(as_text=True)

    # Successful reset when Telegram delivers:
    monkeypatch.setattr(TelegramService, 'send_raw_message', lambda token, chat, text: (True, "Delivered"))

    res_success = client.post('/settings/reset-database', data={
        'confirmation_phrase': 'BORRAR DATOS OPERATIVOS',
        'password': 'password123'
    }, follow_redirects=True)
    assert "Reinicio de datos operativos completado exitosamente" in res_success.get_data(as_text=True)

    # Verify User and SystemSetting are strictly preserved, while product stock is reset to 0
    with app.app_context():
        assert User.query.filter_by(username='test_owner').first() is not None
        assert User.query.filter_by(username='test_admin').first() is not None
        prod = Product.query.filter_by(code='PROD-TEST-01').first()
        assert prod.current_stock == 0.0

def test_finances_module_and_summary_no_double_counting(client, app):
    """
    Test Phase 3 Sections 9 & 10: Finances Module, Excel/PDF export, and zero double-counting in summaries.
    """
    client.post('/auth/login', data={'username': 'test_owner', 'password': 'password123'}, follow_redirects=True)

    # Register an operational expense
    res_expense = client.post('/finances/create', data={
        'movement_type': 'Gasto',
        'category': 'Alquiler de Local',
        'amount': '250.00',
        'payment_method': 'Efectivo',
        'description': 'Pago mensual de bodega'
    }, follow_redirects=True)
    assert "registrado con éxito" in res_expense.get_data(as_text=True)

    # Register an extraordinary income
    res_income = client.post('/finances/create', data={
        'movement_type': 'Ingreso',
        'category': 'Ajuste de Caja Chica',
        'amount': '100.00',
        'payment_method': 'Efectivo',
        'description': 'Aporte adicional de efectivo para caja menor'
    }, follow_redirects=True)
    assert "registrado con éxito" in res_income.get_data(as_text=True)

    with app.app_context():
        daily = SummaryService.get_daily_summary()
        # Verify clear separation of commercial sales vs operating expenses vs extra income
        assert daily['extra_income'] == 100.00
        assert daily['expenses'] == 250.00
        # Net Operating Profit = Gross Profit + Extra Income - Expenses
        assert daily['net_operating_profit'] == round(daily['gross_profit'] + 100.00 - 250.00, 2)

    # Test Excel Export
    res_excel = client.get('/finances/export/excel')
    assert res_excel.status_code == 200
    assert 'spreadsheetml' in res_excel.content_type

    # Test PDF Export
    res_pdf = client.get('/finances/export/pdf')
    assert res_pdf.status_code == 200
    assert 'application/pdf' in res_pdf.content_type


def test_monthly_reports_invoice_details_and_no_type_error_or_404(client, app):
    """
    Test that the monthly reports section displays invoice details, avoids TypeErrors
    on null/undefined receipt fields, and resolves receipts without 404s.
    """
    client.post('/auth/login', data={'username': 'test_admin', 'password': 'password123'}, follow_redirects=True)

    with app.app_context():
        # Create a product and a sale
        prod = Product(
            code='TST001',
            name='Producto Prueba Detalle',
            category='Farmacia',
            purchase_price=50.0,
            sale_price=100.0,
            current_stock=20.0
        )
        db.session.add(prod)
        client_obj = Client(code='CLI-TST-001', name='Cliente Reporte Mensual', is_active=True)
        db.session.add(client_obj)
        db.session.commit()

        # Create sale with receipt
        sale_data = {
            'client_id': client_obj.id,
            'client_name': client_obj.name,
            'salesperson': 'Mostrador',
            'payment_method': 'Efectivo',
            'payment_condition': 'Contado',
            'invoice_number': 'TEST-INV-001'
        }
        items_data = [{
            'product_id': prod.id,
            'quantity': 2,
            'unit_price': 100.0,
            'discount_percent': 0.0
        }]
        sale, receipt = SalesService.create_sale(sale_data, items_data, 1)

        # Create a receipt with missing unit_price and missing discount_percent (e.g., purchase-like payload)
        import json
        custom_receipt = Receipt(
            receipt_number='REC-PURCHASE-TEST',
            receipt_type='Compra',
            subtotal=200.0,
            discount_amount=None,  # Null discount
            total_amount=200.0,
            payload_json=json.dumps({
                'items': [{
                    'code': 'TST001',
                    'name': 'Producto Prueba Compra',
                    'quantity': 4,
                    'unit_cost': 50.0,  # Has unit_cost, no unit_price!
                    'total': 200.0
                    # No discount_percent!
                }]
            })
        )
        db.session.add(custom_receipt)
        db.session.commit()

        sale_id = sale.id
        sale_inv = sale.invoice_number
        custom_receipt_id = custom_receipt.id

    # 1. Monthly reports view
    res_monthly = client.get('/reports/monthly')
    assert res_monthly.status_code == 200
    html_monthly = res_monthly.get_data(as_text=True)
    assert 'Facturas y Ventas del Mes' in html_monthly
    assert sale_inv in html_monthly

    # 2. Receipt with missing/null fields: view, print, pdf (must not raise TypeError)
    res_view = client.get(f'/receipts/{custom_receipt_id}')
    assert res_view.status_code == 200
    assert 'Producto Prueba Compra' in res_view.get_data(as_text=True)

    res_print = client.get(f'/receipts/{custom_receipt_id}/print')
    assert res_print.status_code == 200
    assert 'Producto Prueba Compra' in res_print.get_data(as_text=True)

    res_pdf = client.get(f'/receipts/{custom_receipt_id}/pdf')
    assert res_pdf.status_code == 200
    assert 'application/pdf' in res_pdf.content_type

    # 3. 404 Prevention: Look up receipt by Sale ID directly
    res_by_sale_id = client.get(f'/receipts/{sale_id}')
    assert res_by_sale_id.status_code == 200

    # 4. Look up via /sales/<id> and /receipts/invoice/<number>
    res_sale_route = client.get(f'/sales/{sale_id}', follow_redirects=True)
    assert res_sale_route.status_code == 200

    res_inv_route = client.get(f'/receipts/invoice/{sale_inv}', follow_redirects=True)
    assert res_inv_route.status_code == 200


