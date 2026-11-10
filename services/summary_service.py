from datetime import datetime, date, timedelta, timezone
from sqlalchemy import func
from extensions import db
from models import Sale, SaleItem, Purchase, PurchaseItem, Payment, PurchasePayment, FinancialMovement, InventoryMovement, Product

# Nicaragua timezone UTC-6
MANAGUA_TZ = timezone(timedelta(hours=-6))

def get_managua_today():
    return datetime.now(MANAGUA_TZ).date()

class SummaryService:
    @staticmethod
    def get_daily_summary(target_date=None):
        """
        Generates full commercial & operational summary for a single day without double counting:
        - Distinguishes Sales (Contado vs Crédito) from Cash Received (Contado + Initial Abonos + Subsequent Abonos).
        - Distinguishes Purchases (Contado vs Crédito) from Cash Disbursed (Contado + Initial Payments + Subsequent Supplier Payments).
        """
        if not target_date:
            target_date = get_managua_today()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = datetime.combine(target_date, datetime.max.time())

        # 1. Sales of the day
        sales = Sale.query.filter(
            Sale.created_at >= day_start,
            Sale.created_at <= day_end,
            Sale.status != 'anulada'
        ).all()

        total_sales_amount = round(sum(s.total for s in sales), 2)
        total_cost_of_sales = round(sum(s.cost_of_sales for s in sales), 2)
        gross_profit = round(total_sales_amount - total_cost_of_sales, 2)
        profit_margin = round((gross_profit / total_sales_amount * 100), 1) if total_sales_amount > 0 else 0.0

        cash_sales_collected = round(sum(s.paid_amount for s in sales if not s.is_credit), 2)
        credit_sales_amount = round(sum(s.total for s in sales if s.is_credit), 2)
        # Note: s.paid_amount on a credit sale includes subsequent abonos too!
        # To avoid double counting with Payment records on the same day, initial payment is:
        # s.paid_amount minus sum of confirmed Payment records for that sale
        credit_initial_payments = 0.0
        for s in sales:
            if s.is_credit:
                subsequent_on_sale = sum(p.amount for p in s.payments if p.status != 'anulado')
                init_p = max(0.0, round((s.paid_amount or 0.0) - subsequent_on_sale, 2))
                credit_initial_payments += init_p
        credit_initial_payments = round(credit_initial_payments, 2)

        # 2. Client Abonos (Credit Collections) of the day
        abonos = Payment.query.filter(
            Payment.created_at >= day_start,
            Payment.created_at <= day_end,
            Payment.status != 'anulado'
        ).all()
        total_abonos_collected = round(sum(a.amount for a in abonos), 2)

        # 3. Purchases of the day
        purchases = Purchase.query.filter(
            Purchase.created_at >= day_start,
            Purchase.created_at <= day_end,
            Purchase.status != 'anulada'
        ).all()
        total_purchases_amount = round(sum(p.total for p in purchases), 2)
        cash_purchases_amount = round(sum(p.total for p in purchases if not p.is_credit), 2)
        credit_purchases_amount = round(sum(p.total for p in purchases if p.is_credit), 2)

        credit_purchases_initial_paid = 0.0
        for p in purchases:
            if p.is_credit:
                subsequent_on_purch = sum(pp.amount for pp in p.payments if pp.status != 'anulado')
                init_pp = max(0.0, round((p.paid_amount or 0.0) - subsequent_on_purch, 2))
                credit_purchases_initial_paid += init_pp
        credit_purchases_initial_paid = round(credit_purchases_initial_paid, 2)

        # 4. Supplier Payments (Accounts Payable disbursements) of the day
        supplier_payments = PurchasePayment.query.filter(
            PurchasePayment.created_at >= day_start,
            PurchasePayment.created_at <= day_end,
            PurchasePayment.status != 'anulado'
        ).all()
        total_supplier_payments = round(sum(sp.amount for sp in supplier_payments), 2)

        # 5. Financial movements of the day (Extra Income, Extra Operating Expenses, Returns)
        fin_movements = FinancialMovement.query.filter(
            FinancialMovement.date == target_date,
            FinancialMovement.status != 'anulado'
        ).all()

        extra_income = round(sum(
            f.amount for f in fin_movements
            if f.movement_type == 'Ingreso' and f.category not in ('Venta', 'Abono_Venta', 'Abono_Inicial', 'Devolucion_Proveedor', 'Ajuste_Caja')
        ), 2)
        expenses = round(sum(
            f.amount for f in fin_movements
            if f.movement_type == 'Gasto' and f.category not in ('Compra', 'Pago_Proveedor', 'Devolucion_Cliente', 'Devolucion')
        ), 2)
        returns_refunded = round(sum(
            f.amount for f in fin_movements
            if f.category in ('Devolucion_Cliente', 'Devolucion') and f.movement_type == 'Gasto'
        ), 2)

        # Real Cash Inflow & Outflow (Strict separation: no credit unpaid balance is ever counted as cash)
        total_cash_inflow = round(cash_sales_collected + credit_initial_payments + total_abonos_collected + extra_income, 2)
        total_cash_outflow = round(cash_purchases_amount + credit_purchases_initial_paid + total_supplier_payments + expenses + returns_refunded, 2)
        net_cash_balance = round(total_cash_inflow - total_cash_outflow, 2)

        # Economic Net Operating Profit (P&L): Gross Profit + Extra Income - Operating Expenses
        net_operating_profit = round(gross_profit + extra_income - expenses, 2)

        # 6. Inventory quantities sold vs received
        inv_movements = InventoryMovement.query.filter(
            InventoryMovement.created_at >= day_start,
            InventoryMovement.created_at <= day_end,
            InventoryMovement.status != 'anulado'
        ).all()

        units_sold = round(sum(m.quantity for m in inv_movements if m.operation_type == 'Venta'), 2)
        units_received = round(sum(m.quantity for m in inv_movements if m.operation_type in ('Compra', 'Ajuste_Entrada', 'Devolucion_Cliente')), 2)

        return {
            'date': target_date.strftime('%Y-%m-%d'),
            'date_formatted': target_date.strftime('%d/%m/%Y'),
            'sales_count': len(sales),
            'total_sales_amount': total_sales_amount,
            'cash_sales_collected': cash_sales_collected,
            'credit_sales_amount': credit_sales_amount,
            'credit_initial_payments': credit_initial_payments,
            'abonos_count': len(abonos),
            'total_abonos_collected': total_abonos_collected,
            'total_collections': round(credit_initial_payments + total_abonos_collected, 2),
            'purchases_count': len(purchases),
            'total_purchases_amount': total_purchases_amount,
            'cash_purchases_amount': cash_purchases_amount,
            'credit_purchases_amount': credit_purchases_amount,
            'credit_purchases_initial_paid': credit_purchases_initial_paid,
            'supplier_payments_count': len(supplier_payments),
            'total_supplier_payments': total_supplier_payments,
            'total_purchases_disbursed': round(cash_purchases_amount + credit_purchases_initial_paid + total_supplier_payments, 2),
            'extra_income': extra_income,
            'expenses': expenses,
            'returns_refunded': returns_refunded,
            'total_cash_inflow': total_cash_inflow,
            'total_cash_outflow': total_cash_outflow,
            'net_cash_balance': net_cash_balance,
            'total_cost_of_sales': total_cost_of_sales,
            'gross_profit': gross_profit,
            'net_operating_profit': net_operating_profit,
            'profit_margin': profit_margin,
            'units_sold': units_sold,
            'units_received': units_received,
            'sales_list': sales,
            'purchases_list': purchases,
            'abonos_list': abonos,
            'supplier_payments_list': supplier_payments
        }

    @staticmethod
    def get_monthly_summary(year=None, month=None):
        """
        Generates full monthly commercial summary with Month-over-Month comparison and cash flow breakdown.
        """
        today = get_managua_today()
        if not year:
            year = today.year
        if not month:
            month = today.month

        year = int(year)
        month = int(month)

        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        if month == 1:
            prev_start = date(year - 1, 12, 1)
            prev_end = date(year, 1, 1) - timedelta(days=1)
        else:
            prev_start = date(year, month - 1, 1)
            prev_end = date(year, month, 1) - timedelta(days=1)

        prev_start_dt = datetime.combine(prev_start, datetime.min.time())
        prev_end_dt = datetime.combine(prev_end, datetime.max.time())

        # Current month sales
        sales = Sale.query.filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != 'anulada'
        ).order_by(Sale.created_at.desc()).all()

        total_sales = round(sum(s.total for s in sales), 2)
        cash_sales = round(sum(s.paid_amount for s in sales if not s.is_credit), 2)
        credit_sales = round(sum(s.total for s in sales if s.is_credit), 2)
        credit_init_paid = 0.0
        for s in sales:
            if s.is_credit:
                sub_p = sum(p.amount for p in s.payments if p.status != 'anulado')
                credit_init_paid += max(0.0, round((s.paid_amount or 0.0) - sub_p, 2))
        credit_init_paid = round(credit_init_paid, 2)

        total_cost = round(sum(s.cost_of_sales for s in sales), 2)
        gross_profit = round(total_sales - total_cost, 2)
        avg_ticket = round(total_sales / len(sales), 2) if len(sales) > 0 else 0.0

        # Client Abonos of the month
        abonos = Payment.query.filter(
            Payment.created_at >= start_dt,
            Payment.created_at <= end_dt,
            Payment.status != 'anulado'
        ).all()
        total_abonos = round(sum(a.amount for a in abonos), 2)

        # Current month purchases
        purchases = Purchase.query.filter(
            Purchase.created_at >= start_dt,
            Purchase.created_at <= end_dt,
            Purchase.status != 'anulada'
        ).all()
        total_purchases = round(sum(p.total for p in purchases), 2)
        cash_purchases = round(sum(p.total for p in purchases if not p.is_credit), 2)
        credit_purchases = round(sum(p.total for p in purchases if p.is_credit), 2)
        credit_purch_init_paid = 0.0
        for p in purchases:
            if p.is_credit:
                sub_pp = sum(pp.amount for pp in p.payments if pp.status != 'anulado')
                credit_purch_init_paid += max(0.0, round((p.paid_amount or 0.0) - sub_pp, 2))
        credit_purch_init_paid = round(credit_purch_init_paid, 2)

        # Supplier payments of the month
        supplier_payments = PurchasePayment.query.filter(
            PurchasePayment.created_at >= start_dt,
            PurchasePayment.created_at <= end_dt,
            PurchasePayment.status != 'anulado'
        ).all()
        total_supplier_payments = round(sum(sp.amount for sp in supplier_payments), 2)

        # Financial movements of the month
        fin_movements = FinancialMovement.query.filter(
            FinancialMovement.date >= start_date,
            FinancialMovement.date <= end_date,
            FinancialMovement.status != 'anulado'
        ).all()

        total_expenses = round(sum(
            e.amount for e in fin_movements
            if e.movement_type == 'Gasto' and e.category not in ('Compra', 'Pago_Proveedor', 'Devolucion_Cliente', 'Devolucion')
        ), 2)
        total_extra_income = round(sum(
            i.amount for i in fin_movements
            if i.movement_type == 'Ingreso' and i.category not in ('Venta', 'Abono_Venta', 'Abono_Inicial', 'Devolucion_Proveedor', 'Ajuste_Caja')
        ), 2)
        returns_refunded = round(sum(
            f.amount for f in fin_movements
            if f.category in ('Devolucion_Cliente', 'Devolucion') and f.movement_type == 'Gasto'
        ), 2)

        total_cash_inflow = round(cash_sales + credit_init_paid + total_abonos + total_extra_income, 2)
        total_cash_outflow = round(cash_purchases + credit_purch_init_paid + total_supplier_payments + total_expenses + returns_refunded, 2)
        net_cash_flow = round(total_cash_inflow - total_cash_outflow, 2)

        net_operating_profit = round(gross_profit + total_extra_income - total_expenses, 2)

        # Previous month sales for comparison
        prev_sales = Sale.query.filter(
            Sale.created_at >= prev_start_dt,
            Sale.created_at <= prev_end_dt,
            Sale.status != 'anulada'
        ).all()
        prev_total_sales = round(sum(s.total for s in prev_sales), 2)
        prev_cost = round(sum(s.cost_of_sales for s in prev_sales), 2)
        prev_gross_profit = round(prev_total_sales - prev_cost, 2)

        if prev_total_sales > 0:
            sales_growth_pct = round(((total_sales - prev_total_sales) / prev_total_sales) * 100, 1)
        else:
            sales_growth_pct = 100.0 if total_sales > 0 else 0.0

        if prev_gross_profit > 0:
            profit_growth_pct = round(((gross_profit - prev_gross_profit) / prev_gross_profit) * 100, 1)
        else:
            profit_growth_pct = 100.0 if gross_profit > 0 else 0.0

        sold_stats = db.session.query(
            SaleItem.product_name_snapshot,
            SaleItem.product_code_snapshot,
            func.sum(SaleItem.quantity).label('units_sold'),
            func.sum(SaleItem.total).label('revenue')
        ).join(Sale, SaleItem.sale_id == Sale.id).filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != 'anulada'
        ).group_by(SaleItem.product_code_snapshot, SaleItem.product_name_snapshot).order_by(func.sum(SaleItem.quantity).desc()).all()

        top_selling = [{
            'name': r[0],
            'code': r[1],
            'units': float(r[2]),
            'revenue': float(r[3])
        } for r in sold_stats[:5]]

        least_selling = [{
            'name': r[0],
            'code': r[1],
            'units': float(r[2]),
            'revenue': float(r[3])
        } for r in sold_stats[-5:]] if len(sold_stats) > 5 else []

        month_names = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

        return {
            'year': year,
            'month': month,
            'month_name': month_names[month - 1],
            'start_date': start_date.strftime('%d/%m/%Y'),
            'end_date': end_date.strftime('%d/%m/%Y'),
            'sales_count': len(sales),
            'sales_list': sales,
            'total_sales': total_sales,
            'cash_sales': cash_sales,
            'credit_sales': credit_sales,
            'total_abonos': round(credit_init_paid + total_abonos, 2),
            'total_cost': total_cost,
            'gross_profit': gross_profit,
            'profit_margin_pct': round((gross_profit / total_sales * 100), 1) if total_sales > 0 else 0.0,
            'avg_ticket': avg_ticket,
            'total_purchases': total_purchases,
            'cash_purchases': cash_purchases,
            'credit_purchases': credit_purchases,
            'total_supplier_payments': round(credit_purch_init_paid + total_supplier_payments, 2),
            'total_expenses': total_expenses,
            'total_extra_income': total_extra_income,
            'returns_refunded': returns_refunded,
            'total_cash_inflow': total_cash_inflow,
            'total_cash_outflow': total_cash_outflow,
            'net_cash_flow': net_cash_flow,
            'net_operating_profit': net_operating_profit,
            'prev_month_sales': prev_total_sales,
            'sales_growth_pct': sales_growth_pct,
            'profit_growth_pct': profit_growth_pct,
            'top_selling': top_selling,
            'least_selling': least_selling
        }

    @staticmethod
    def get_trend_data(period='30d', custom_start=None, custom_end=None):
        """
        Calculates time-series trends (Sales, Purchases, Expenses) with previous period comparison.
        """
        today = get_managua_today()
        if period == '7d':
            days_count = 7
            start_date = today - timedelta(days=6)
            end_date = today
        elif period == '3m':
            days_count = 90
            start_date = today - timedelta(days=89)
            end_date = today
        elif period == 'custom' and custom_start and custom_end:
            start_date = datetime.strptime(custom_start, '%Y-%m-%d').date()
            end_date = datetime.strptime(custom_end, '%Y-%m-%d').date()
            days_count = (end_date - start_date).days + 1
        else:
            days_count = 30
            start_date = today - timedelta(days=29)
            end_date = today

        labels = []
        sales_data = []
        purchases_data = []
        expenses_data = []

        curr = start_date
        while curr <= end_date:
            labels.append(curr.strftime('%d/%m'))
            c_start = datetime.combine(curr, datetime.min.time())
            c_end = datetime.combine(curr, datetime.max.time())

            s_sum = db.session.query(func.coalesce(func.sum(Sale.total), 0.0)).filter(
                Sale.created_at >= c_start,
                Sale.created_at <= c_end,
                Sale.status != 'anulada'
            ).scalar()

            p_sum = db.session.query(func.coalesce(func.sum(Purchase.total), 0.0)).filter(
                Purchase.created_at >= c_start,
                Purchase.created_at <= c_end,
                Purchase.status != 'anulada'
            ).scalar()

            e_sum = db.session.query(func.coalesce(func.sum(FinancialMovement.amount), 0.0)).filter(
                FinancialMovement.date == curr,
                FinancialMovement.movement_type == 'Gasto',
                FinancialMovement.status != 'anulado'
            ).scalar()

            sales_data.append(round(float(s_sum), 2))
            purchases_data.append(round(float(p_sum), 2))
            expenses_data.append(round(float(e_sum), 2))

            curr += timedelta(days=1)

        prev_start = start_date - timedelta(days=days_count)
        prev_end = start_date - timedelta(days=1)
        prev_sales_sum = db.session.query(func.coalesce(func.sum(Sale.total), 0.0)).filter(
            Sale.created_at >= datetime.combine(prev_start, datetime.min.time()),
            Sale.created_at <= datetime.combine(prev_end, datetime.max.time()),
            Sale.status != 'anulada'
        ).scalar()

        total_sales_current = sum(sales_data)
        growth_vs_previous = round(((total_sales_current - float(prev_sales_sum)) / float(prev_sales_sum) * 100), 1) if float(prev_sales_sum) > 0 else 0.0

        return {
            'labels': labels,
            'sales': sales_data,
            'purchases': purchases_data,
            'expenses': expenses_data,
            'total_sales': round(total_sales_current, 2),
            'total_purchases': round(sum(purchases_data), 2),
            'total_expenses': round(sum(expenses_data), 2),
            'growth_vs_previous': growth_vs_previous,
            'period': period
        }
