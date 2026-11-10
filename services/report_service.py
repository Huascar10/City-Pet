from datetime import datetime, date, timedelta
from sqlalchemy import func
from extensions import db
from models import Product, Sale, SaleItem, Purchase, Payment, PurchasePayment, FinancialMovement, InventoryMovement, Client, Supplier

class ReportService:
    @staticmethod
    def get_dashboard_metrics(period_days=30):
        """
        Calculates real-time business KPIs strictly from database records for the Inicio dashboard.
        """
        today = date.today()
        start_of_today = datetime.combine(today, datetime.min.time())
        end_of_today = datetime.combine(today, datetime.max.time())
        start_date = start_of_today - timedelta(days=period_days)

        # Inventory KPIs
        total_products = Product.query.filter_by(is_active=True).count()
        total_units = db.session.query(func.coalesce(func.sum(Product.current_stock), 0.0)).filter(Product.is_active == True).scalar()
        inventory_valuation = db.session.query(
            func.coalesce(func.sum(Product.current_stock * Product.purchase_price), 0.0)
        ).filter(Product.is_active == True).scalar()

        # Stock alert counts
        out_of_stock_count = Product.query.filter(Product.is_active == True, Product.current_stock <= 0).count()
        low_stock_count = Product.query.filter(
            Product.is_active == True,
            Product.current_stock > 0,
            Product.current_stock < Product.min_stock
        ).count()

        # Today's Sales
        today_sales_list = Sale.query.filter(
            Sale.status == 'confirmada',
            Sale.created_at >= start_of_today,
            Sale.created_at <= end_of_today
        ).all()
        today_sales_total = round(sum(s.total for s in today_sales_list), 2)
        today_cost_of_sales = round(sum(s.cost_of_sales for s in today_sales_list), 2)
        today_sales_count = len(today_sales_list)
        today_gross_profit = round(today_sales_total - today_cost_of_sales, 2)
        today_cash_sales = round(sum(s.total for s in today_sales_list if not s.is_credit), 2)
        today_credit_sales = round(sum(s.total for s in today_sales_list if s.is_credit), 2)

        # Today's Collections (Cobros recibidos: abonos a créditos + abonos iniciales de créditos hoy)
        today_abonos = Payment.query.filter(
            Payment.status == 'confirmado',
            Payment.created_at >= start_of_today,
            Payment.created_at <= end_of_today
        ).all()
        today_abonos_sum = sum(a.amount for a in today_abonos)
        today_credit_init = 0.0
        for s in today_sales_list:
            if s.is_credit:
                sub_p = sum(p.amount for p in s.payments if p.status != 'anulado')
                today_credit_init += max(0.0, round((s.paid_amount or 0.0) - sub_p, 2))
        today_collections = round(today_abonos_sum + today_credit_init, 2)

        # Today's Purchases
        today_purchases_list = Purchase.query.filter(
            Purchase.status == 'confirmada',
            Purchase.created_at >= start_of_today,
            Purchase.created_at <= end_of_today
        ).all()
        today_purchases_total = round(sum(p.total for p in today_purchases_list), 2)
        today_purchases_count = len(today_purchases_list)

        # Today's Supplier Payments
        today_supp_payments = PurchasePayment.query.filter(
            PurchasePayment.status == 'confirmado',
            PurchasePayment.created_at >= start_of_today,
            PurchasePayment.created_at <= end_of_today
        ).all()
        today_supplier_payments = round(sum(sp.amount for sp in today_supp_payments), 2)

        # Today's Finances (Incomes & Expenses)
        today_fin_movs = FinancialMovement.query.filter(
            FinancialMovement.date == today,
            FinancialMovement.status != 'anulado'
        ).all()
        today_incomes = round(sum(f.amount for f in today_fin_movs if f.movement_type == 'Ingreso'), 2)
        today_expenses = round(sum(f.amount for f in today_fin_movs if f.movement_type == 'Gasto'), 2)
        today_extra_expenses = round(sum(
            f.amount for f in today_fin_movs
            if f.movement_type == 'Gasto' and f.category not in ('Compra', 'Pago_Proveedor', 'Devolucion_Cliente', 'Devolucion')
        ), 2)

        # Available Cash Balance (Dinero disponible según movimientos registrados en caja)
        all_incomes = db.session.query(func.coalesce(func.sum(FinancialMovement.amount), 0.0)).filter(
            FinancialMovement.movement_type == 'Ingreso',
            FinancialMovement.status != 'anulado'
        ).scalar()
        all_expenses = db.session.query(func.coalesce(func.sum(FinancialMovement.amount), 0.0)).filter(
            FinancialMovement.movement_type == 'Gasto',
            FinancialMovement.status != 'anulado'
        ).scalar()
        available_cash_balance = round(float(all_incomes) - float(all_expenses), 2)

        # Accounts Receivable (Cuentas por cobrar pendientes)
        active_credit_sales = Sale.query.filter(Sale.status == 'confirmada').all()
        pending_sales_list = [s for s in active_credit_sales if s.balance_due > 0.001]
        overdue_sales_list = [s for s in pending_sales_list if s.is_overdue]
        total_receivables = round(sum(s.balance_due for s in pending_sales_list), 2)

        # Accounts Payable (Cuentas por pagar pendientes)
        active_purchases = Purchase.query.filter(Purchase.status == 'confirmada').all()
        pending_purchases_list = [p for p in active_purchases if p.balance_due > 0.001]
        overdue_purchases_list = [p for p in pending_purchases_list if p.is_overdue]
        total_payables = round(sum(p.balance_due for p in pending_purchases_list), 2)

        # Period Sales
        period_sales = db.session.query(
            func.coalesce(func.sum(Sale.total), 0.0)
        ).filter(Sale.status == 'confirmada', Sale.created_at >= start_date).scalar()

        # Recent Movements & Sales
        recent_movements = InventoryMovement.query.order_by(
            InventoryMovement.created_at.desc()
        ).limit(8).all()
        recent_sales = Sale.query.order_by(Sale.created_at.desc()).limit(6).all()

        # Low stock products list
        low_stock_products = Product.query.filter(
            Product.is_active == True,
            Product.current_stock < Product.min_stock
        ).order_by(Product.current_stock.asc()).limit(8).all()

        # Chart: Last 7 days sales
        chart_labels = []
        chart_values = []
        for d in range(6, -1, -1):
            day_target = today - timedelta(days=d)
            day_start = datetime.combine(day_target, datetime.min.time())
            day_end = datetime.combine(day_target, datetime.max.time())
            
            day_sum = db.session.query(func.coalesce(func.sum(Sale.total), 0.0)).filter(
                Sale.status == 'confirmada',
                Sale.created_at >= day_start,
                Sale.created_at <= day_end
            ).scalar()
            
            chart_labels.append(day_target.strftime('%d/%m'))
            chart_values.append(round(float(day_sum), 2))

        # Top 5 selling products in period
        top_sellers = db.session.query(
            SaleItem.product_name_snapshot,
            func.sum(SaleItem.quantity).label('total_qty'),
            func.sum(SaleItem.total).label('total_revenue')
        ).join(Sale).filter(
            Sale.status == 'confirmada',
            Sale.created_at >= start_date
        ).group_by(SaleItem.product_name_snapshot).order_by(
            func.sum(SaleItem.quantity).desc()
        ).limit(5).all()

        return {
            'total_products': total_products,
            'total_units': round(float(total_units), 2),
            'inventory_valuation': round(float(inventory_valuation), 2),
            'out_of_stock_count': out_of_stock_count,
            'low_stock_count': low_stock_count,
            'today_sales_total': today_sales_total,
            'today_sales_count': today_sales_count,
            'today_cash_sales': today_cash_sales,
            'today_credit_sales': today_credit_sales,
            'today_gross_profit': today_gross_profit,
            'today_collections': today_collections,
            'today_abonos_count': len(today_abonos),
            'today_purchases_total': today_purchases_total,
            'today_purchases_count': today_purchases_count,
            'today_supplier_payments': today_supplier_payments,
            'today_extra_expenses': today_extra_expenses,
            'today_incomes': today_incomes,
            'today_expenses': today_expenses,
            'available_cash_balance': available_cash_balance,
            'available_cash': available_cash_balance,
            'total_receivables': total_receivables,
            'accounts_receivable': total_receivables,
            'pending_receivables_count': len(pending_sales_list),
            'overdue_receivables_count': len(overdue_sales_list),
            'pending_sales_list': pending_sales_list[:6],
            'total_payables': total_payables,
            'accounts_payable': total_payables,
            'pending_payables_count': len(pending_purchases_list),
            'overdue_payables_count': len(overdue_purchases_list),
            'pending_purchases_list': pending_purchases_list[:6],
            'period_sales': round(float(period_sales), 2),
            'period_days': period_days,
            'recent_movements': recent_movements,
            'recent_sales': recent_sales,
            'low_stock_products': low_stock_products,
            'chart_labels': chart_labels,
            'chart_values': chart_values,
            'top_sellers': top_sellers
        }

    @staticmethod
    def get_sales_report(start_date=None, end_date=None, client_id=None, salesperson=None):
        query = Sale.query.filter(Sale.status == 'confirmada')
        if start_date:
            query = query.filter(Sale.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            query = query.filter(Sale.created_at <= datetime.combine(end_date, datetime.max.time()))
        if client_id:
            query = query.filter(Sale.client_id == client_id)
        if salesperson:
            query = query.filter(Sale.salesperson.ilike(f"%{salesperson}%"))

        sales = query.order_by(Sale.created_at.desc()).all()
        total_revenue = sum(s.total for s in sales)
        total_cost = sum(s.cost_of_sales for s in sales)
        gross_profit = total_revenue - total_cost

        return {
            'sales': sales,
            'count': len(sales),
            'total_revenue': round(total_revenue, 2),
            'total_cost': round(total_cost, 2),
            'gross_profit': round(gross_profit, 2)
        }

    @staticmethod
    def get_inventory_audit_report():
        """Returns discrepancies between physical count and current calculated stock."""
        products = Product.query.filter_by(is_active=True).all()
        items = []
        for p in products:
            items.append({
                'code': p.code,
                'name': p.name,
                'category': p.category,
                'current_stock': p.current_stock,
                'physical_stock': p.physical_stock,
                'difference': p.difference,
                'status': p.status,
                'valuation': p.inventory_value
            })
        return items
