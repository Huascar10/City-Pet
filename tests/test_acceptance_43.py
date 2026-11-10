import os
import json
from datetime import date, timedelta
import pytest

from app import create_app
from extensions import db
from models import (
    User, Client, Supplier, Product, Sale, SaleItem, Payment, CreditException,
    Purchase, PurchaseItem, PurchasePayment, InventoryMovement, FinancialMovement,
    Receipt, SystemSetting, AuditLog, LoginAttempt
)
from services.sales_service import SalesService, CreditLimitExceededError
from services.purchase_service import PurchaseService
from services.payment_service import PaymentService
from services.inventory_service import InventoryService
from services.returns_service import ReturnsService
from services.reconciliation_service import ReconciliationService
from services.summary_service import SummaryService, get_managua_today
from services.report_service import ReportService
from services.excel_service import ExcelService
from services.crypto_service import CryptoService
from services.telegram_service import TelegramService
from services.backup_service import BackupService


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        owner = User(
            username='owner_test',
            full_name='Propietario Test',
            role='propietario',
            is_active=True,
            can_authorize_credit=True
        )
        owner.set_password('OwnerPass123!')

        admin = User(
            username='admin_test',
            full_name='Admin Test',
            role='administrador',
            is_active=True,
            can_authorize_credit=False
        )
        admin.set_password('AdminPass123!')

        supervisor = User(
            username='sup_test',
            full_name='Supervisor Credito',
            role='administrador',
            is_active=True,
            can_authorize_credit=True
        )
        supervisor.set_password('SupPass123!')

        emp = User(
            username='emp_test',
            full_name='Empleado Caja',
            role='empleado',
            is_active=True,
            can_authorize_credit=False
        )
        emp.set_password('EmpPass123!')

        db.session.add_all([owner, admin, supervisor, emp])

        supplier = Supplier(
            code='PROV-TEST-01',
            company_name='Novavet Test Lab',
            ruc='J0310000111111',
            is_active=True
        )
        db.session.add(supplier)
        db.session.flush()

        prod = Product(
            code='CP-TEST-001',
            name='AMOXIPET TEST 250MG',
            category='Antibióticos',
            unit='Frasco',
            purchase_price=100.0,
            sale_price=200.0,
            current_stock=50.0,
            physical_stock=50.0,
            min_stock=10.0,
            supplier_id=supplier.id,
            is_active=True
        )
        db.session.add(prod)

        client = Client(
            code='CP-CLI-001',
            name='VETERINARIA SAN FRANCISCO',
            trade_name='VET SAN FRANCISCO',
            ruc='0010101900001A',
            credit_limit=1000.0,
            credit_days=30,
            is_active=True
        )
        db.session.add(client)
        db.session.commit()

        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username, password):
    return client.post('/auth/login', data={'username': username, 'password': password}, follow_redirects=True)


# ==============================================================================
# SECCIÓN A: VENTAS (Pruebas 1 a 7)
# ==============================================================================

def test_01_cash_sale_inventory_deduction(app):
    """1. Venta al contado con descuento correcto de inventario."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()
        initial_stock = p.current_stock

        sale, receipt = SalesService.create_sale(
            user_id=u.id,
            client_data={'name': 'Cliente Contado'},
            items_data=[{'product_id': p.id, 'quantity': 5, 'unit_price': 200.0}],
            payment_method='Efectivo',
            payment_condition='Contado'
        )
        assert sale.total == 1000.0
        assert p.current_stock == initial_stock - 5.0
        mov = InventoryMovement.query.filter_by(sale_id=sale.id, product_id=p.id).first()
        assert mov is not None and mov.quantity == 5.0 and mov.new_stock == 45.0


def test_02_cash_sale_financial_inflow(app):
    """2. Venta al contado con ingreso financiero correcto."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()
        sale, _ = SalesService.create_sale(
            user_id=u.id,
            client_data={'name': 'Cliente Contado'},
            items_data=[{'product_id': p.id, 'quantity': 3, 'unit_price': 200.0}],
            payment_method='Efectivo',
            payment_condition='Contado'
        )
        fin = FinancialMovement.query.filter_by(sale_id=sale.id, status='confirmado').first()
        assert fin is not None
        assert fin.movement_type == 'Ingreso'
        assert fin.amount == 600.0


def test_03_credit_sale_within_limit(app):
    """3. Venta a crédito dentro del límite permitido."""
    with app.app_context():
        u = User.query.filter_by(username='emp_test').first()
        c = Client.query.filter_by(code='CP-CLI-001').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        sale, _ = SalesService.create_sale(
            user_id=u.id,
            client_data={'client_id': c.id, 'name': c.name},
            items_data=[{'product_id': p.id, 'quantity': 4, 'unit_price': 200.0}],
            payment_method='Crédito',
            payment_condition='Crédito 30 días',
            initial_payment=0.0
        )
        assert sale.total == 800.0
        assert sale.balance_due == 800.0
        assert c.total_debt == 800.0
        assert c.available_credit == 200.0


def test_04_credit_sale_blocked_when_exceeding_limit(app):
    """4. Bloqueo de venta a crédito cuando se supera el límite."""
    with app.app_context():
        u = User.query.filter_by(username='emp_test').first()
        c = Client.query.filter_by(code='CP-CLI-001').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # Client limit is 1000.0; try selling 1200.0 on credit without supervisor auth
        with pytest.raises(CreditLimitExceededError) as exc_info:
            SalesService.create_sale(
                user_id=u.id,
                client_data={'client_id': c.id, 'name': c.name},
                items_data=[{'product_id': p.id, 'quantity': 6, 'unit_price': 200.0}],
                payment_method='Crédito',
                payment_condition='Crédito 30 días',
                initial_payment=0.0
            )
        assert exc_info.value.evaluation['exceeds_limit'] is True
        assert c.total_debt == 0.0
        assert p.current_stock == 50.0


def test_05_credit_sale_exceeding_limit_with_supervisor_authorization(app):
    """5. Venta a crédito superando el límite con autorización de supervisor."""
    with app.app_context():
        emp = User.query.filter_by(username='emp_test').first()
        c = Client.query.filter_by(code='CP-CLI-001').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        sale, _ = SalesService.create_sale(
            user_id=emp.id,
            client_data={'client_id': c.id, 'name': c.name},
            items_data=[{'product_id': p.id, 'quantity': 7, 'unit_price': 200.0}],
            payment_method='Crédito',
            payment_condition='Crédito 30 días',
            initial_payment=0.0,
            credit_authorization={
                'username': 'sup_test',
                'password': 'SupPass123!',
                'reason': 'Cliente VIP autorizado por gerencia comercial'
            }
        )
        assert sale.total == 1400.0
        assert sale.credit_exception_id is not None
        exc = CreditException.query.get(sale.credit_exception_id)
        assert exc is not None
        assert exc.excess_amount == 400.0
        assert exc.reason == 'Cliente VIP autorizado por gerencia comercial'


def test_06_sale_blocked_when_insufficient_stock(app):
    """6. Bloqueo de venta sin existencias suficientes."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        with pytest.raises(ValueError, match="insuficientes"):
            SalesService.create_sale(
                user_id=u.id,
                client_data={'name': 'Mostrador'},
                items_data=[{'product_id': p.id, 'quantity': 999, 'unit_price': 200.0}],
                payment_method='Efectivo',
                payment_condition='Contado'
            )
        assert p.current_stock == 50.0


def test_07_void_sale_reverses_inventory_and_finances(app):
    """7. Anulación de venta y reversión correcta de inventario y finanzas."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        sale, _ = SalesService.create_sale(
            user_id=u.id,
            client_data={'name': 'Cliente Contado'},
            items_data=[{'product_id': p.id, 'quantity': 5, 'unit_price': 200.0}],
            payment_method='Efectivo',
            payment_condition='Contado'
        )
        assert p.current_stock == 45.0

        SalesService.void_sale(sale.id, u.id, reason="Error de digitación en factura")
        assert sale.status == 'anulada'
        assert p.current_stock == 50.0
        fin = FinancialMovement.query.filter_by(sale_id=sale.id, category='Venta').first()
        assert fin.status == 'anulado'


# ==============================================================================
# SECCIÓN B: COBROS DE CLIENTES (Pruebas 8 a 11)
# ==============================================================================

def test_08_09_10_11_client_collections_and_liquidation_lifecycle(app):
    """
    8. Abono parcial de cliente.
    9. Segundo abono de cliente.
    10. Liquidación total de deuda de cliente.
    11. Rechazo de abono mayor que la deuda pendiente.
    """
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        c = Client.query.filter_by(code='CP-CLI-001').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # Venta a crédito de C$ 1,000 sin abono inicial
        sale, _ = SalesService.create_sale(
            user_id=u.id,
            client_data={'client_id': c.id, 'name': c.name},
            items_data=[{'product_id': p.id, 'quantity': 5, 'unit_price': 200.0}],
            payment_method='Crédito',
            payment_condition='Crédito 30 días',
            initial_payment=0.0
        )
        assert sale.balance_due == 1000.0
        assert sale.payment_status == 'Pendiente'

        # Prueba 8: Primer abono parcial de C$ 400
        pay1, rec1 = PaymentService.register_abono(
            sale_id=sale.id, amount=400.0, payment_method='Efectivo', user_id=u.id
        )
        assert pay1.previous_balance == 1000.0
        assert pay1.new_balance == 600.0
        assert sale.balance_due == 600.0
        assert sale.payment_status == 'Abonado'
        assert c.total_debt == 600.0
        assert c.available_credit == 400.0

        # Prueba 9: Segundo abono parcial de C$ 350
        pay2, rec2 = PaymentService.register_abono(
            sale_id=sale.id, amount=350.0, payment_method='Transferencia', user_id=u.id
        )
        assert pay2.previous_balance == 600.0
        assert pay2.new_balance == 250.0
        assert sale.balance_due == 250.0
        assert sale.payment_status == 'Abonado'

        # Prueba 11: Rechazo de abono mayor que la deuda pendiente (Intentar abonar C$ 300 cuando debe C$ 250)
        with pytest.raises(ValueError, match="excede el saldo pendiente"):
            PaymentService.register_abono(
                sale_id=sale.id, amount=300.0, payment_method='Efectivo', user_id=u.id
            )
        assert sale.balance_due == 250.0

        # Prueba 10: Liquidación total de deuda (Abonar los C$ 250 restantes)
        pay3, rec3 = PaymentService.register_abono(
            sale_id=sale.id, amount=250.0, payment_method='Efectivo', user_id=u.id
        )
        assert pay3.new_balance == 0.0
        assert sale.balance_due == 0.0
        assert sale.is_paid is True
        assert sale.payment_status == 'Liquidado'
        assert c.total_debt == 0.0
        assert c.available_credit == 1000.0


# ==============================================================================
# SECCIÓN C: COMPRAS Y PROVEEDORES (Pruebas 12 a 18)
# ==============================================================================

def test_12_cash_purchase_increases_stock_and_records_outflow(app):
    """12. Compra al contado con aumento de inventario y salida de dinero."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        s = Supplier.query.filter_by(code='PROV-TEST-01').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        purchase, _ = PurchaseService.create_purchase(
            supplier_id=s.id,
            items_data=[{'product_id': p.id, 'quantity': 10, 'unit_cost': 100.0}],
            user_id=u.id,
            payment_condition='Contado',
            payment_method='Efectivo'
        )
        assert purchase.total == 1000.0
        assert purchase.paid_amount == 1000.0
        assert purchase.balance_due == 0.0
        assert purchase.payment_status == 'Liquidado'
        assert p.current_stock == 60.0

        fin = FinancialMovement.query.filter_by(purchase_id=purchase.id, status='confirmado').first()
        assert fin is not None and fin.movement_type == 'Gasto' and fin.amount == 1000.0


def test_13_14_15_16_17_mandatory_credit_purchase_500_200_300_scenario(app):
    """
    13. Compra a crédito de $500 con aumento de inventario y deuda de $500 sin salida total de caja.
    14. Abono inicial o pago parcial de $200 dejando saldo pendiente de $300.
    15. Pago final de $300 dejando saldo $0 y estado liquidado.
    16. Rechazo de pago mayor que la deuda pendiente al proveedor.
    17. Visualización correcta de deuda en el perfil del proveedor.
    """
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        s = Supplier.query.filter_by(code='PROV-TEST-01').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # Prueba 13: Compra a crédito de $500 con pago inicial $0
        purchase, _ = PurchaseService.create_purchase(
            supplier_id=s.id,
            items_data=[{'product_id': p.id, 'quantity': 5, 'unit_cost': 100.0}],
            user_id=u.id,
            payment_condition='Crédito 30 días',
            payment_method='Crédito',
            initial_payment=0.0
        )
        assert purchase.total == 500.0
        assert purchase.paid_amount == 0.0
        assert purchase.balance_due == 500.0
        assert purchase.payment_status == 'Pendiente'
        assert p.current_stock == 55.0
        # Verificar que NO salió dinero de caja porque el pago inicial fue $0
        fin_outflows = FinancialMovement.query.filter_by(purchase_id=purchase.id, status='confirmado').all()
        assert len(fin_outflows) == 0

        # Prueba 17 (parte 1): Deuda en el perfil del proveedor es $500
        assert s.total_debt == 500.0
        assert len(s.pending_purchases) == 1

        # Prueba 14: Pago parcial de $200 dejando saldo pendiente de $300
        sp1, rec1 = PaymentService.register_supplier_payment(
            purchase_id=purchase.id,
            amount=200.0,
            payment_method='Transferencia',
            user_id=u.id,
            reference='TRF-200'
        )
        assert sp1.previous_balance == 500.0
        assert sp1.amount == 200.0
        assert sp1.new_balance == 300.0
        assert purchase.paid_amount == 200.0
        assert purchase.balance_due == 300.0
        assert purchase.payment_status == 'Abonado'
        assert s.total_debt == 300.0

        # Verificar que la salida financiera en caja es exactamente $200
        fin_sp1 = FinancialMovement.query.filter_by(purchase_payment_id=sp1.id, status='confirmado').first()
        assert fin_sp1 is not None and fin_sp1.amount == 200.0 and fin_sp1.movement_type == 'Gasto'

        # Prueba 16: Rechazo de pago mayor que la deuda pendiente ($400 > $300)
        with pytest.raises(ValueError, match="saldo pendiente"):
            PaymentService.register_supplier_payment(
                purchase_id=purchase.id,
                amount=400.0,
                payment_method='Efectivo',
                user_id=u.id
            )
        assert purchase.balance_due == 300.0

        # Prueba 15: Pago final de $300 dejando saldo $0 y estado Liquidado
        sp2, rec2 = PaymentService.register_supplier_payment(
            purchase_id=purchase.id,
            amount=300.0,
            payment_method='Efectivo',
            user_id=u.id,
            reference='EFE-300'
        )
        assert sp2.previous_balance == 300.0
        assert sp2.new_balance == 0.0
        assert purchase.paid_amount == 500.0
        assert purchase.balance_due == 0.0
        assert purchase.is_paid is True
        assert purchase.payment_status == 'Liquidado'
        assert s.total_debt == 0.0
        assert len(s.pending_purchases) == 0


def test_18_void_purchase_reverses_stock_and_finances(app):
    """18. Anulación de compra y reversión correcta."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        s = Supplier.query.filter_by(code='PROV-TEST-01').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        purchase, _ = PurchaseService.create_purchase(
            supplier_id=s.id,
            items_data=[{'product_id': p.id, 'quantity': 8, 'unit_cost': 100.0}],
            user_id=u.id,
            payment_condition='Crédito 30 días',
            payment_method='Efectivo',
            initial_payment=250.0
        )
        assert p.current_stock == 58.0
        assert purchase.paid_amount == 250.0

        PurchaseService.void_purchase(purchase.id, u.id, reason="Factura duplicada del proveedor")
        assert purchase.status == 'anulada'
        assert p.current_stock == 50.0
        assert s.total_debt == 0.0


# ==============================================================================
# SECCIÓN D: INVENTARIO (Pruebas 19 a 24)
# ==============================================================================

def test_19_20_inventory_inflow_and_outflow(app):
    """19. Entrada de inventario. 20. Salida de inventario."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # 19. Entrada
        mov_in = InventoryService.record_movement(
            product_id=p.id,
            operation_type='Ajuste_Entrada',
            quantity=10.0,
            user_id=u.id,
            reason='Ingreso por bonificación de laboratorio'
        )
        assert p.current_stock == 60.0
        assert mov_in.new_stock == 60.0

        # 20. Salida
        mov_out = InventoryService.record_movement(
            product_id=p.id,
            operation_type='Danado_Merma',
            quantity=4.0,
            user_id=u.id,
            reason='Frascos rotos en transporte'
        )
        assert p.current_stock == 56.0
        assert mov_out.new_stock == 56.0


def test_21_22_client_and_supplier_returns(app):
    """21. Devolución de cliente. 22. Devolución a proveedor."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        c = Client.query.filter_by(code='CP-CLI-001').first()
        s = Supplier.query.filter_by(code='PROV-TEST-01').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # 21. Devolución de cliente (+2 unidades al stock)
        mov_c, rec_c = ReturnsService.process_client_return(
            product_id=p.id,
            quantity=2,
            unit_refund_price=200.0,
            client_id=c.id,
            reason='Producto cambiado por otra presentación',
            user_id=u.id
        )
        assert p.current_stock == 52.0
        assert rec_c.receipt_type in ('Devolucion', 'Devolucion_Cliente')
        assert rec_c.payload['type'] == 'Devolución de Cliente'

        # 22. Devolución a proveedor (-3 unidades del stock)
        mov_s, rec_s = ReturnsService.process_supplier_return(
            product_id=p.id,
            quantity=3,
            supplier_id=s.id,
            unit_cost_reimbursement=100.0,
            reason='Lote próximo a vencer devuelto a laboratorio',
            user_id=u.id
        )
        assert p.current_stock == 49.0
        assert rec_s.receipt_type in ('Devolucion', 'Devolucion_Proveedor')
        assert rec_s.payload['type'] == 'Devolución a Proveedor'


def test_23_24_physical_adjustment_and_three_way_reconciliation(app):
    """
    23. Ajuste por conteo físico con justificación.
    24. Conciliación entre inventario teórico, sistema y conteo físico.
    """
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # Sin motivo debe fallar
        with pytest.raises(ValueError, match="motivo"):
            ReconciliationService.apply_adjustment(product_id=p.id, target_stock=42.0, reason="abc", user_id=u.id)

        # Con motivo auditable válido ajusta tanto current_stock como physical_stock
        mov = ReconciliationService.apply_adjustment(
            product_id=p.id,
            target_stock=42.0,
            reason="Conteo físico trimestral verificado en bodega principal",
            user_id=u.id
        )
        assert mov is not None
        assert p.current_stock == 42.0
        assert p.physical_stock == 42.0

        rec_data = ReconciliationService.get_product_reconciliation_data(product_id=p.id)
        assert len(rec_data) == 1
        item = rec_data[0]
        assert item['current_stock'] == 42.0
        assert item['physical_stock'] == 42.0
        assert 'theoretical_stock' in item
        assert 'hist_in' in item


# ==============================================================================
# SECCIÓN E: FINANZAS Y REPORTES (Pruebas 25 a 30)
# ==============================================================================

def test_25_26_27_28_29_30_financial_integrity_and_reports(app, client):
    """
    25. Registro de ingreso adicional.
    26. Registro de gasto operativo.
    27. Verificación de no duplicidad entre ventas, abonos, compras y pagos.
    28. Resumen financiero diario correcto.
    29. Resumen financiero mensual correcto.
    30. Cálculo correcto de cuentas por cobrar y cuentas por pagar.
    """
    login(client, 'owner_test', 'OwnerPass123!')
    today = get_managua_today()

    # 25. Registro de ingreso adicional (C$ 500)
    client.post('/finances/create', data={
        'movement_type': 'Ingreso',
        'category': 'Otro Ingreso',
        'amount': '500.00',
        'payment_method': 'Efectivo',
        'description': 'Aporte de cambio para caja chica',
        'date': today.strftime('%Y-%m-%d')
    }, follow_redirects=True)

    # 26. Registro de gasto operativo (C$ 150)
    client.post('/finances/create', data={
        'movement_type': 'Gasto',
        'category': 'Servicios Básicos (Luz/Agua/Internet)',
        'amount': '150.00',
        'payment_method': 'Efectivo',
        'description': 'Pago recibo de agua',
        'date': today.strftime('%Y-%m-%d')
    }, follow_redirects=True)

    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        c = Client.query.filter_by(code='CP-CLI-001').first()
        s = Supplier.query.filter_by(code='PROV-TEST-01').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # Venta de contado: C$ 400 (Entra C$ 400 a caja)
        SalesService.create_sale(
            user_id=u.id,
            client_data={'name': 'Contado'},
            items_data=[{'product_id': p.id, 'quantity': 2, 'unit_price': 200.0}],
            payment_method='Efectivo',
            payment_condition='Contado'
        )

        # Venta a crédito: C$ 600 con abono inicial C$ 100, y luego abono de C$ 200 (Queda por cobrar C$ 300)
        credit_sale, _ = SalesService.create_sale(
            user_id=u.id,
            client_data={'client_id': c.id, 'name': c.name},
            items_data=[{'product_id': p.id, 'quantity': 3, 'unit_price': 200.0}],
            payment_method='Crédito',
            payment_condition='Crédito 30 días',
            initial_payment=100.0
        )
        PaymentService.register_abono(sale_id=credit_sale.id, amount=200.0, payment_method='Efectivo', user_id=u.id)

        # Compra a crédito: C$ 500 con abono inicial C$ 0, y luego pago parcial de C$ 200 (Queda por pagar C$ 300)
        credit_purch, _ = PurchaseService.create_purchase(
            supplier_id=s.id,
            items_data=[{'product_id': p.id, 'quantity': 5, 'unit_cost': 100.0}],
            user_id=u.id,
            payment_condition='Crédito 30 días',
            payment_method='Crédito',
            initial_payment=0.0
        )
        PaymentService.register_supplier_payment(purchase_id=credit_purch.id, amount=200.0, payment_method='Efectivo', user_id=u.id)

        # 27 & 28: Resumen financiero diario sin doble conteo
        daily = SummaryService.get_daily_summary(today)
        assert daily['total_sales_amount'] == 1000.0  # 400 contado + 600 crédito
        assert daily['cash_sales_collected'] == 400.0
        assert daily['credit_initial_payments'] == 100.0
        assert daily['total_abonos_collected'] == 200.0
        assert daily['extra_income'] == 500.0
        # Total Cash Inflow = 400 (contado) + 100 (abono inicial) + 200 (abono posterior) + 500 (ingreso extra) = 1200.0
        assert daily['total_cash_inflow'] == 1200.0

        # Total Cash Outflow = 0 (compra contado) + 0 (abono inicial compra) + 200 (pago proveedor) + 150 (gasto op) = 350.0
        assert daily['total_purchases_amount'] == 500.0
        assert daily['total_supplier_payments'] == 200.0
        assert daily['expenses'] == 150.0
        assert daily['total_cash_outflow'] == 350.0
        assert daily['net_cash_balance'] == 850.0

        # 29: Resumen mensual consistente
        monthly = SummaryService.get_monthly_summary(today.year, today.month)
        assert monthly['total_sales'] == 1000.0
        assert monthly['total_purchases'] == 500.0
        assert monthly['total_cash_inflow'] == 1200.0
        assert monthly['total_cash_outflow'] == 350.0
        assert monthly['net_cash_flow'] == 850.0

        # 30: Cálculo exacto de Cuentas por Cobrar y Cuentas por Pagar
        dash = ReportService.get_dashboard_metrics()
        assert dash['accounts_receivable'] == 300.0
        assert dash['accounts_payable'] == 300.0
        assert dash['available_cash'] == 850.0


# ==============================================================================
# SECCIÓN F: DATOS Y SEGURIDAD (Pruebas 31 a 38)
# ==============================================================================

def test_31_32_33_34_excel_import_clients_suppliers_and_duplicates(app):
    """
    31. Importación correcta de INVENTARIO NUEVO.xlsx.
    32. Importación de los 10 clientes antes omitidos.
    33. Asociación correcta de compras a Novavet y CampoVet.
    34. Detección de duplicados en importación.
    """
    excel_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'INVENTARIO NUEVO.xlsx')
    assert os.path.exists(excel_path)

    with app.app_context():
        # Clear seed test items so we test clean import of INVENTARIO NUEVO.xlsx
        db.session.query(Product).delete()
        db.session.query(Client).delete()
        db.session.query(Supplier).delete()
        db.session.commit()

        u = User.query.filter_by(username='owner_test').first()

        # Primera importación
        rep1 = ExcelService.import_citypet_master_excel(excel_path, user_id=u.id)
        assert rep1['products_created'] == 38
        assert rep1['clients_created'] == 341
        assert rep1['clients_recovered'] == 10
        assert Supplier.query.count() == 2

        novavet = Supplier.query.filter_by(company_name='Novavet').first()
        campovet = Supplier.query.filter_by(company_name='CampoVet').first()
        assert novavet is not None and campovet is not None
        assert InventoryMovement.query.filter_by(supplier_id=novavet.id).count() == 305
        assert InventoryMovement.query.filter_by(supplier_id=campovet.id).count() == 1

        # Verificar que los 10 clientes antes omitidos existen ahora en la base de datos
        for omitted_code in ['CP-C0330', 'CP-C0331', 'CP-C0332', 'CP-C0333', 'CP-C0334', 'CP-C0335', 'CP-C0338', 'CP-C0339', 'CP-C0340', 'CP-C0341']:
            assert Client.query.filter_by(code=omitted_code).first() is not None

        # Prueba 34: Segunda importación detecta duplicados y NO duplica productos, clientes ni movimientos
        rep2 = ExcelService.import_citypet_master_excel(excel_path, user_id=u.id)
        assert rep2['products_created'] == 0
        assert rep2['clients_created'] == 0
        assert rep2['movements_imported'] == 0
        assert rep2['duplicates_skipped'] == 2690
        assert Product.query.count() == 38
        assert Client.query.count() == 341
        assert InventoryMovement.query.count() == 2690


def test_35_telegram_token_encrypted_at_rest(app):
    """35. Cifrado del token de Telegram."""
    with app.app_context():
        secret_token = "888777666:AAH_SecretTelegramBotToken_XYZ987"
        TelegramService.save_bot_token(secret_token)

        raw_in_db = TelegramService.get_raw_stored_token()
        assert raw_in_db != secret_token
        assert raw_in_db.startswith("ENCv1:")
        assert secret_token not in raw_in_db

        cfg = TelegramService.get_config()
        assert cfg['bot_token'] == secret_token
        assert cfg['has_token'] is True


def test_36_login_brute_force_lockout(app, client):
    """36. Bloqueo por intentos fallidos de login."""
    for _ in range(5):
        res = client.post('/auth/login', data={'username': 'emp_test', 'password': 'WrongPassword!'})
        assert res.status_code in (200, 401, 429)

    with app.app_context():
        emp = User.query.filter_by(username='emp_test').first()
        assert emp.failed_login_attempts >= 5
        assert emp.is_locked is True

    # Incluso con la contraseña correcta debe rechazar mientras esté bloqueado
    res_locked = client.post('/auth/login', data={'username': 'emp_test', 'password': 'EmpPass123!'}, follow_redirects=True)
    assert b'bloqueada' in res_locked.data or res_locked.status_code == 429


def test_37_backend_role_permissions_owner_admin_employee(app, client):
    """37. Permisos de Propietario, Administrador y Empleado en backend."""
    # Empleado no puede acceder a compras, finanzas ni configuración
    login(client, 'emp_test', 'EmpPass123!')
    assert client.get('/sales/pos').status_code == 200
    assert 'Acceso restringido' in client.get('/purchases/', follow_redirects=True).get_data(as_text=True)
    assert 'Acceso restringido' in client.get('/finances/', follow_redirects=True).get_data(as_text=True)
    assert 'Acceso restringido' in client.get('/settings/users', follow_redirects=True).get_data(as_text=True)
    client.get('/auth/logout')

    # Administrador puede acceder a compras y finanzas, pero no a usuarios/respaldos/Telegram de propietario
    login(client, 'admin_test', 'AdminPass123!')
    assert client.get('/purchases/').status_code == 200
    assert client.get('/finances/').status_code == 200
    assert 'Acceso restringido' in client.get('/settings/users', follow_redirects=True).get_data(as_text=True)
    assert 'Acceso restringido' in client.get('/settings/backups', follow_redirects=True).get_data(as_text=True)
    client.get('/auth/logout')

    # Propietario tiene acceso total
    login(client, 'owner_test', 'OwnerPass123!')
    assert client.get('/settings/users').status_code == 200
    assert client.get('/settings/backups').status_code == 200
    assert client.get('/settings/telegram').status_code == 200


def test_38_full_relational_backup_and_isolated_restore(app):
    """38. Respaldo completo y restauración íntegra en base de datos de prueba."""
    with app.app_context():
        u = User.query.filter_by(username='owner_test').first()
        c = Client.query.filter_by(code='CP-CLI-001').first()
        p = Product.query.filter_by(code='CP-TEST-001').first()

        # Crear una venta y un abono para tener relaciones completas
        sale, _ = SalesService.create_sale(
            user_id=u.id,
            client_data={'client_id': c.id, 'name': c.name},
            items_data=[{'product_id': p.id, 'quantity': 2, 'unit_price': 200.0}],
            payment_method='Crédito',
            payment_condition='Crédito 30 días',
            initial_payment=50.0
        )
        PaymentService.register_abono(sale_id=sale.id, amount=100.0, payment_method='Efectivo', user_id=u.id)

        backup_payload = BackupService.generate_full_backup_dict(exported_by='owner_test', include_media=False)
        is_valid, msg = BackupService.verify_backup_payload(backup_payload)
        assert is_valid is True, msg

        # Probar restauración en base de datos aislada en memoria
        ok, verify_msg, counts = BackupService.verify_backup_in_isolated_db(backup_payload)
        assert ok is True, verify_msg
        assert counts['sales'] == 1
        assert counts['payments'] == 1
        assert counts['products'] == 1
        assert counts['clients'] == 1


# ==============================================================================
# SECCIÓN G: INTERFAZ Y MÓVIL (Pruebas 39 a 43)
# ==============================================================================

def test_39_40_41_42_43_ui_navigation_profiles_tutorial_and_mobile(app, client):
    """
    39. Navegación simplificada.
    40. Perfil unificado de cliente.
    41. Perfil unificado de proveedor.
    42. Tutorial paso a paso funcional.
    43. Uso completo en vista móvil.
    """
    login(client, 'owner_test', 'OwnerPass123!')

    # 39. Navegación simplificada (7 secciones + menú de engranaje)
    res_dash = client.get('/')
    html_dash = res_dash.data.decode('utf-8')
    assert res_dash.status_code == 200
    for nav_section in ['Inicio', 'Ventas', 'Compras', 'Inventario', 'Clientes', 'Proveedores', 'Reportes']:
        assert nav_section in html_dash
    assert 'settingsGearMenuBtn' in html_dash

    # 40. Perfil unificado de cliente
    with app.app_context():
        c = Client.query.filter_by(code='CP-CLI-001').first()
        c_id = c.id
        s = Supplier.query.filter_by(code='PROV-TEST-01').first()
        s_id = s.id

    res_cli = client.get(f'/clients/{c_id}/history')
    html_cli = res_cli.data.decode('utf-8')
    assert res_cli.status_code == 200
    assert 'Límite de Crédito' in html_cli
    assert 'Deuda Total Actual' in html_cli
    assert 'Crédito Disponible' in html_cli
    assert 'Facturas Pendientes' in html_cli
    assert 'Historial de Abonos' in html_cli

    # 41. Perfil unificado de proveedor
    res_supp = client.get(f'/suppliers/{s_id}/history')
    html_supp = res_supp.data.decode('utf-8')
    assert res_supp.status_code == 200
    assert 'Total Adeudado al Proveedor' in html_supp
    assert 'Compras Pendientes de Pago' in html_supp
    assert 'Historial de Pagos' in html_supp

    # 42. Tutorial paso a paso funcional
    assert 'Tutorial de esta ventana' in html_dash
    assert 'CityPetInteractiveTour.showWindowGuide()' in html_dash
    res_js = client.get('/static/js/citypet-interactive-tour.js')
    html_js = res_js.data.decode('utf-8')
    assert 'getStepsForCurrentWindow' in html_js
    assert 'prevStep' in html_js and 'nextStep' in html_js

    # 43. Uso completo en vista móvil (barra inferior móvil, viewport responsive, tablas adaptables)
    assert 'citypet-bottom-nav d-lg-none' in html_dash
    assert 'width=device-width, initial-scale=1.0' in html_dash
    assert 'table-responsive' in html_dash
