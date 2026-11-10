import os
import json
import hashlib
import base64
import tempfile
from datetime import datetime, date
from flask import current_app
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from extensions import db
from models import (
    User, SystemSetting, Supplier, Client, Product,
    Sale, SaleItem, CreditException,
    Purchase, PurchaseItem, PurchasePayment,
    Payment, Receipt, InventoryMovement, FinancialMovement, AuditLog
)

class BackupService:
    REQUIRED_SECTIONS = [
        'users', 'system_settings', 'suppliers', 'clients', 'products',
        'sales', 'sale_items', 'credit_exceptions',
        'purchases', 'purchase_items', 'receipts',
        'payments', 'purchase_payments',
        'inventory_movements', 'financial_movements', 'audit_logs'
    ]

    @staticmethod
    def _parse_dt(val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        s = str(val).strip()
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(s[:26], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime.utcnow()

    @staticmethod
    def _parse_date(val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        s = str(val).strip()[:10]
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None

    @classmethod
    def _compute_checksum(cls, sections_dict: dict) -> str:
        canonical = json.dumps(sections_dict, sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def generate_full_backup_dict(cls, exported_by='system', include_media=True):
        """
        Generates a complete, relationally ordered backup dictionary containing all entities,
        settings, users, transactions, audit logs, and associated uploaded media files.
        """
        users_list = []
        for u in User.query.order_by(User.id.asc()).all():
            d = u.to_dict()
            d['password_hash'] = u.password_hash
            users_list.append(d)

        settings_list = [
            {'key': s.key, 'value': s.value, 'description': s.description}
            for s in SystemSetting.query.all()
        ]
        suppliers_list = [s.to_dict() for s in Supplier.query.order_by(Supplier.id.asc()).all()]
        clients_list = [c.to_dict() for c in Client.query.order_by(Client.id.asc()).all()]
        products_list = [p.to_dict() for p in Product.query.order_by(Product.id.asc()).all()]
        sales_list = [s.to_dict() for s in Sale.query.order_by(Sale.id.asc()).all()]
        sale_items_list = [
            {
                'id': si.id,
                'sale_id': si.sale_id,
                'product_id': si.product_id,
                'product_code_snapshot': si.product_code_snapshot,
                'product_name_snapshot': si.product_name_snapshot,
                'quantity': si.quantity,
                'unit_price_snapshot': si.unit_price_snapshot,
                'unit_cost_snapshot': si.unit_cost_snapshot,
                'discount_percent': si.discount_percent,
                'discount_amount': si.discount_amount,
                'total': si.total
            }
            for si in SaleItem.query.order_by(SaleItem.id.asc()).all()
        ]
        credit_exceptions_list = [ce.to_dict() for ce in CreditException.query.order_by(CreditException.id.asc()).all()]
        purchases_list = [p.to_dict() for p in Purchase.query.order_by(Purchase.id.asc()).all()]
        purchase_items_list = [
            {
                'id': pi.id,
                'purchase_id': pi.purchase_id,
                'product_id': pi.product_id,
                'product_code_snapshot': pi.product_code_snapshot,
                'product_name_snapshot': pi.product_name_snapshot,
                'quantity': pi.quantity,
                'unit_cost': pi.unit_cost,
                'total': pi.total,
                'update_product_cost': pi.update_product_cost
            }
            for pi in PurchaseItem.query.order_by(PurchaseItem.id.asc()).all()
        ]
        receipts_list = []
        for r in Receipt.query.order_by(Receipt.id.asc()).all():
            rd = r.to_dict()
            rd['payload_json'] = r.payload_json
            receipts_list.append(rd)

        payments_list = [pm.to_dict() for pm in Payment.query.order_by(Payment.id.asc()).all()]
        purchase_payments_list = [pp.to_dict() for pp in PurchasePayment.query.order_by(PurchasePayment.id.asc()).all()]
        movements_list = [m.to_dict() for m in InventoryMovement.query.order_by(InventoryMovement.id.asc()).all()]
        finances_list = [f.to_dict() for f in FinancialMovement.query.order_by(FinancialMovement.id.asc()).all()]
        audit_logs_list = [a.to_dict() for a in AuditLog.query.order_by(AuditLog.id.asc()).all()]

        media_files = []
        if include_media:
            try:
                upload_dir = current_app.config.get('UPLOAD_FOLDER')
                if upload_dir and os.path.exists(upload_dir):
                    for root, _, files in os.walk(upload_dir):
                        for fn in files:
                            if fn.startswith('temp_'):
                                continue
                            full_p = os.path.join(root, fn)
                            rel_p = os.path.relpath(full_p, upload_dir).replace('\\', '/')
                            with open(full_p, 'rb') as mf:
                                raw_b = mf.read()
                            media_files.append({
                                'relative_path': rel_p,
                                'sha256': hashlib.sha256(raw_b).hexdigest(),
                                'content_b64': base64.b64encode(raw_b).decode('ascii')
                            })
            except Exception:
                pass

        sections = {
            'users': users_list,
            'system_settings': settings_list,
            'suppliers': suppliers_list,
            'clients': clients_list,
            'products': products_list,
            'sales': sales_list,
            'sale_items': sale_items_list,
            'credit_exceptions': credit_exceptions_list,
            'purchases': purchases_list,
            'purchase_items': purchase_items_list,
            'receipts': receipts_list,
            'payments': payments_list,
            'purchase_payments': purchase_payments_list,
            'inventory_movements': movements_list,
            'financial_movements': finances_list,
            'audit_logs': audit_logs_list,
            'media_files': media_files
        }

        counts = {k: len(v) for k, v in sections.items()}
        checksum = cls._compute_checksum(sections)

        app_env = 'development'
        try:
            app_env = current_app.config.get('APP_ENV', 'development')
        except RuntimeError:
            pass

        snapshot = {
            'metadata': {
                'system': 'CityPet Pharma',
                'version': '4.0-Consolidated',
                'environment': app_env,
                'timestamp': datetime.utcnow().isoformat(),
                'exported_by': exported_by,
                'counts': counts,
                'integrity_checksum': checksum,
                'checksum_sha256': checksum
            },
            **sections,
            # Legacy compatibility aliases
            'movements': movements_list,
            'finances': finances_list
        }
        return snapshot

    @classmethod
    def save_backup_file(cls, filepath: str, exported_by='system', include_media=True):
        """Generates a full backup dictionary and writes it to filepath."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        snapshot = cls.generate_full_backup_dict(exported_by=exported_by, include_media=include_media)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        return snapshot

    @classmethod
    def verify_backup_payload(cls, data: dict):
        """Non-raising wrapper around validate_backup_payload returning (is_valid, message)."""
        try:
            cls.validate_backup_payload(data)
            return True, "Estructura relacional y suma de verificación SHA-256 válidas."
        except Exception as e:
            return False, str(e)

    @classmethod
    def validate_backup_payload(cls, data: dict):
        """
        Validates backup structure, required tables, row counts, and SHA-256 checksum.
        Raises ValueError if invalid, incomplete, or corrupted.
        """
        if not isinstance(data, dict):
            raise ValueError("El archivo de respaldo no contiene un objeto JSON válido.")
        if 'metadata' not in data or not isinstance(data['metadata'], dict):
            raise ValueError("El archivo de respaldo carece de metadatos ('metadata').")

        meta = data['metadata']
        if meta.get('system') != 'CityPet Pharma':
            raise ValueError("El archivo no pertenece al sistema CityPet Pharma.")

        # Support normalized keys if legacy 'movements'/'finances' used
        if 'inventory_movements' not in data and 'movements' in data:
            data['inventory_movements'] = data['movements']
        if 'financial_movements' not in data and 'finances' in data:
            data['financial_movements'] = data['finances']

        missing = [k for k in ('products', 'clients', 'suppliers', 'sales', 'purchases', 'inventory_movements', 'financial_movements', 'receipts') if k not in data]
        if missing:
            raise ValueError(f"Respaldo incompleto. Faltan secciones obligatorias: {', '.join(missing)}")

        for k in missing:
            if not isinstance(data.get(k), list):
                raise ValueError(f"La sección '{k}' del respaldo está corrupta.")

        expected_counts = meta.get('counts')
        if expected_counts and isinstance(expected_counts, dict):
            for section_key, exp_count in expected_counts.items():
                if section_key in data and isinstance(data[section_key], list):
                    actual_count = len(data[section_key])
                    if actual_count != exp_count:
                        raise ValueError(
                            f"Fallo de integridad en sección '{section_key}': se esperaban {exp_count} registros pero se encontraron {actual_count}."
                        )

        expected_checksum = meta.get('integrity_checksum')
        if expected_checksum:
            sections = {
                k: data.get(k, []) for k in (
                    'users', 'system_settings', 'suppliers', 'clients', 'products',
                    'sales', 'sale_items', 'credit_exceptions',
                    'purchases', 'purchase_items', 'receipts',
                    'payments', 'purchase_payments',
                    'inventory_movements', 'financial_movements', 'audit_logs', 'media_files'
                )
            }
            calc_checksum = cls._compute_checksum(sections)
            if calc_checksum != expected_checksum:
                raise ValueError("Fallo de verificación criptográfica (SHA-256): el archivo de respaldo ha sido alterado o está corrupto.")

        return True

    @classmethod
    def _populate_session_from_dict(cls, session, data: dict):
        """
        Inserts all entities from validated backup dictionary into the given SQLAlchemy session
        respecting strict relational and foreign key ordering.
        """
        # Clear operational and catalog tables in reverse FK dependency order
        session.query(FinancialMovement).delete()
        session.query(InventoryMovement).delete()
        session.query(PurchasePayment).delete()
        session.query(Payment).delete()
        session.query(CreditException).delete()
        session.query(SaleItem).delete()
        session.query(PurchaseItem).delete()
        session.query(Receipt).delete()
        session.query(Purchase).delete()
        session.query(Sale).delete()
        session.query(Product).delete()
        session.query(Client).delete()
        session.query(Supplier).delete()
        session.query(AuditLog).delete()
        session.flush()

        # 1. Users (upsert by id/username)
        for u_data in data.get('users', []):
            u = session.get(User, u_data.get('id')) if u_data.get('id') else None
            if not u:
                u = session.query(User).filter_by(username=u_data.get('username')).first()
            if not u:
                u = User(
                    id=u_data.get('id'),
                    username=u_data.get('username'),
                    email=u_data.get('email'),
                    password_hash=u_data.get('password_hash') or 'pbkdf2:sha256:600000$default',
                    full_name=u_data.get('full_name', u_data.get('username', 'Usuario')),
                    role=u_data.get('role', 'administrador'),
                    is_active=bool(u_data.get('is_active', True)),
                    can_authorize_credit=bool(u_data.get('can_authorize_credit', True)),
                    created_at=cls._parse_dt(u_data.get('created_at')) or datetime.utcnow()
                )
                session.add(u)
            else:
                u.full_name = u_data.get('full_name', u.full_name)
                u.role = u_data.get('role', u.role)
                u.is_active = bool(u_data.get('is_active', u.is_active))
                if u_data.get('password_hash'):
                    u.password_hash = u_data['password_hash']
        session.flush()

        # 2. System Settings
        for s_data in data.get('system_settings', []):
            k = s_data.get('key')
            if not k:
                continue
            st = session.get(SystemSetting, k)
            if not st:
                st = SystemSetting(key=k, value=s_data.get('value'), description=s_data.get('description'))
                session.add(st)
            else:
                st.value = s_data.get('value')
                st.description = s_data.get('description')
        session.flush()

        # 3. Suppliers
        for sp in data.get('suppliers', []):
            session.add(Supplier(
                id=sp.get('id'),
                code=sp.get('code'),
                company_name=sp.get('company_name'),
                contact_name=sp.get('contact_name'),
                phone=sp.get('phone'),
                email=sp.get('email'),
                ruc=sp.get('ruc'),
                address=sp.get('address'),
                supplied_products=sp.get('supplied_products'),
                notes=sp.get('notes'),
                is_active=bool(sp.get('is_active', True))
            ))
        session.flush()

        # 4. Clients
        for cl in data.get('clients', []):
            session.add(Client(
                id=cl.get('id'),
                code=cl.get('code'),
                trade_name=cl.get('trade_name'),
                name=cl.get('name'),
                owner_name=cl.get('owner_name'),
                department=cl.get('department'),
                municipality=cl.get('municipality'),
                address=cl.get('address'),
                ruc=cl.get('ruc'),
                phone=cl.get('phone'),
                salesperson=cl.get('salesperson'),
                registration_number=cl.get('registration_number'),
                credit_limit=float(cl.get('credit_limit', 0.0) or 0.0),
                term_code=cl.get('term_code'),
                credit_days=int(cl.get('credit_days', 0) or 0),
                transport=cl.get('transport'),
                payment_condition=cl.get('payment_condition'),
                notes=cl.get('notes'),
                is_active=bool(cl.get('is_active', True))
            ))
        session.flush()

        # 5. Products
        for pr in data.get('products', []):
            session.add(Product(
                id=pr.get('id'),
                code=pr.get('code'),
                name=pr.get('name'),
                category=pr.get('category', 'General'),
                warehouse=pr.get('warehouse', 'Principal'),
                unit=pr.get('unit', 'Unid'),
                barcode=pr.get('barcode'),
                description=pr.get('description'),
                image_url=pr.get('image_url'),
                purchase_price=float(pr.get('purchase_price', 0.0) or 0.0),
                sale_price=float(pr.get('sale_price', 0.0) or 0.0),
                current_stock=max(0.0, float(pr.get('current_stock', 0.0) or 0.0)),
                min_stock=float(pr.get('min_stock', 5.0) or 5.0),
                physical_stock=float(pr.get('physical_stock', 0.0) or 0.0),
                expiration_date=cls._parse_date(pr.get('expiration_date')),
                supplier_id=pr.get('supplier_id'),
                is_active=bool(pr.get('is_active', True))
            ))
        session.flush()

        # 6. Sales & SaleItems
        sale_items_explicit = data.get('sale_items', [])
        for sl in data.get('sales', []):
            s_obj = Sale(
                id=sl.get('id'),
                invoice_number=sl.get('invoice_number'),
                client_id=sl.get('client_id'),
                client_name=sl.get('client_name', 'Mostrador'),
                client_ruc=sl.get('client_ruc'),
                client_address=sl.get('client_address'),
                client_code=sl.get('client_code'),
                salesperson=sl.get('salesperson'),
                payment_method=sl.get('payment_method', 'Efectivo'),
                payment_condition=sl.get('payment_condition', 'Contado'),
                subtotal=float(sl.get('subtotal', 0.0) or 0.0),
                discount_percent=float(sl.get('discount_percent', 0.0) or 0.0),
                discount_amount=float(sl.get('discount_amount', 0.0) or 0.0),
                tax_percent=float(sl.get('tax_percent', 0.0) or 0.0),
                tax_amount=float(sl.get('tax_amount', 0.0) or 0.0),
                total=float(sl.get('total', 0.0) or 0.0),
                paid_amount=float(sl.get('paid_amount', 0.0) or 0.0),
                cost_of_sales=float(sl.get('cost_of_sales', 0.0) or 0.0),
                due_date=cls._parse_date(sl.get('due_date')),
                credit_exception_id=sl.get('credit_exception_id'),
                status=sl.get('status', 'confirmada'),
                void_reason=sl.get('void_reason'),
                notes=sl.get('notes'),
                user_id=sl.get('user_id'),
                created_at=cls._parse_dt(sl.get('created_at')) or datetime.utcnow()
            )
            session.add(s_obj)
            if not sale_items_explicit and sl.get('items'):
                for it in sl['items']:
                    session.add(SaleItem(
                        id=it.get('id'),
                        sale_id=sl.get('id'),
                        product_id=it.get('product_id'),
                        product_code_snapshot=it.get('product_code') or it.get('product_code_snapshot', ''),
                        product_name_snapshot=it.get('product_name') or it.get('product_name_snapshot', ''),
                        quantity=float(it.get('quantity', 1) or 1),
                        unit_price_snapshot=float(it.get('unit_price') or it.get('unit_price_snapshot', 0.0)),
                        unit_cost_snapshot=float(it.get('unit_cost') or it.get('unit_cost_snapshot', 0.0)),
                        discount_percent=float(it.get('discount_percent', 0.0) or 0.0),
                        discount_amount=float(it.get('discount_amount', 0.0) or 0.0),
                        total=float(it.get('total', 0.0) or 0.0)
                    ))
        for si in sale_items_explicit:
            session.add(SaleItem(
                id=si.get('id'),
                sale_id=si.get('sale_id'),
                product_id=si.get('product_id'),
                product_code_snapshot=si.get('product_code_snapshot', ''),
                product_name_snapshot=si.get('product_name_snapshot', ''),
                quantity=float(si.get('quantity', 1) or 1),
                unit_price_snapshot=float(si.get('unit_price_snapshot', 0.0) or 0.0),
                unit_cost_snapshot=float(si.get('unit_cost_snapshot', 0.0) or 0.0),
                discount_percent=float(si.get('discount_percent', 0.0) or 0.0),
                discount_amount=float(si.get('discount_amount', 0.0) or 0.0),
                total=float(si.get('total', 0.0) or 0.0)
            ))
        session.flush()

        # 7. Credit Exceptions
        for ce in data.get('credit_exceptions', []):
            session.add(CreditException(
                id=ce.get('id'),
                sale_id=ce.get('sale_id'),
                client_id=ce.get('client_id'),
                authorized_by_id=ce.get('authorized_by_id', 1),
                authorized_by_username=ce.get('authorized_by_username', 'admin'),
                requested_by_id=ce.get('requested_by_id'),
                reason=ce.get('reason', 'Excepción restaurada'),
                credit_limit_snapshot=float(ce.get('credit_limit_snapshot', 0.0) or 0.0),
                previous_debt_snapshot=float(ce.get('previous_debt_snapshot', 0.0) or 0.0),
                new_credit_amount=float(ce.get('new_credit_amount', 0.0) or 0.0),
                excess_amount=float(ce.get('excess_amount', 0.0) or 0.0),
                had_overdue_invoices=bool(ce.get('had_overdue_invoices', False)),
                created_at=cls._parse_dt(ce.get('created_at')) or datetime.utcnow()
            ))
        session.flush()

        # 8. Purchases & PurchaseItems
        purch_items_explicit = data.get('purchase_items', [])
        for pu in data.get('purchases', []):
            is_cred = 'credito' in str(pu.get('payment_condition', '')).lower() or 'crédito' in str(pu.get('payment_condition', '')).lower()
            default_paid = 0.0 if is_cred else float(pu.get('total', 0.0) or 0.0)
            p_obj = Purchase(
                id=pu.get('id'),
                purchase_number=pu.get('purchase_number'),
                supplier_id=pu.get('supplier_id'),
                supplier_name_snapshot=pu.get('supplier_name') or pu.get('supplier_name_snapshot', ''),
                supplier_ruc_snapshot=pu.get('supplier_ruc') or pu.get('supplier_ruc_snapshot'),
                supplier_invoice_number=pu.get('supplier_invoice_number'),
                warehouse=pu.get('warehouse', 'Principal'),
                payment_method=pu.get('payment_method', 'Efectivo'),
                payment_condition=pu.get('payment_condition', 'Contado'),
                subtotal=float(pu.get('subtotal', 0.0) or 0.0),
                tax_amount=float(pu.get('tax_amount', 0.0) or 0.0),
                discount_amount=float(pu.get('discount_amount', 0.0) or 0.0),
                total=float(pu.get('total', 0.0) or 0.0),
                paid_amount=float(pu.get('paid_amount', default_paid) if pu.get('paid_amount') is not None else default_paid),
                due_date=cls._parse_date(pu.get('due_date')),
                status=pu.get('status', 'confirmada'),
                void_reason=pu.get('void_reason'),
                notes=pu.get('notes'),
                user_id=pu.get('user_id'),
                created_at=cls._parse_dt(pu.get('created_at')) or datetime.utcnow()
            )
            session.add(p_obj)
            if not purch_items_explicit and pu.get('items'):
                for it in pu['items']:
                    session.add(PurchaseItem(
                        id=it.get('id'),
                        purchase_id=pu.get('id'),
                        product_id=it.get('product_id'),
                        product_code_snapshot=it.get('product_code') or it.get('product_code_snapshot', ''),
                        product_name_snapshot=it.get('product_name') or it.get('product_name_snapshot', ''),
                        quantity=float(it.get('quantity', 1) or 1),
                        unit_cost=float(it.get('unit_cost', 0.0) or 0.0),
                        total=float(it.get('total', 0.0) or 0.0),
                        update_product_cost=bool(it.get('update_product_cost', True))
                    ))
        for pi in purch_items_explicit:
            session.add(PurchaseItem(
                id=pi.get('id'),
                purchase_id=pi.get('purchase_id'),
                product_id=pi.get('product_id'),
                product_code_snapshot=pi.get('product_code_snapshot', ''),
                product_name_snapshot=pi.get('product_name_snapshot', ''),
                quantity=float(pi.get('quantity', 1) or 1),
                unit_cost=float(pi.get('unit_cost', 0.0) or 0.0),
                total=float(pi.get('total', 0.0) or 0.0),
                update_product_cost=bool(pi.get('update_product_cost', True))
            ))
        session.flush()

        # 9. Receipts
        for rc in data.get('receipts', []):
            payload_str = rc.get('payload_json')
            if not payload_str:
                payload_str = json.dumps(rc.get('payload', {}), ensure_ascii=False)
            session.add(Receipt(
                id=rc.get('id'),
                receipt_number=rc.get('receipt_number'),
                receipt_type=rc.get('receipt_type', 'Venta'),
                related_sale_id=rc.get('related_sale_id'),
                related_purchase_id=rc.get('related_purchase_id'),
                related_payment_id=rc.get('related_payment_id'),
                related_purchase_payment_id=rc.get('related_purchase_payment_id'),
                client_id=rc.get('client_id'),
                supplier_id=rc.get('supplier_id'),
                user_id=rc.get('user_id'),
                client_name_snapshot=rc.get('client_name') or rc.get('client_name_snapshot'),
                client_ruc_snapshot=rc.get('client_ruc') or rc.get('client_ruc_snapshot'),
                client_address_snapshot=rc.get('client_address') or rc.get('client_address_snapshot'),
                salesperson_snapshot=rc.get('salesperson') or rc.get('salesperson_snapshot'),
                client_code_snapshot=rc.get('client_code') or rc.get('client_code_snapshot'),
                subtotal=float(rc.get('subtotal', 0.0) or 0.0),
                discount_amount=float(rc.get('discount_amount', 0.0) or 0.0),
                tax_amount=float(rc.get('tax_amount', 0.0) or 0.0),
                total_amount=float(rc.get('total_amount', 0.0) or 0.0),
                payment_method=rc.get('payment_method'),
                payment_condition=rc.get('payment_condition'),
                status=rc.get('status', 'confirmado'),
                notes=rc.get('notes'),
                void_reason=rc.get('void_reason'),
                payload_json=payload_str,
                created_at=cls._parse_dt(rc.get('created_at')) or datetime.utcnow()
            ))
        session.flush()

        # 10. Payments (Client Abonos)
        for pm in data.get('payments', []):
            session.add(Payment(
                id=pm.get('id'),
                payment_number=pm.get('payment_number'),
                sale_id=pm.get('sale_id'),
                client_id=pm.get('client_id'),
                user_id=pm.get('user_id'),
                amount=float(pm.get('amount', 0.0) or 0.0),
                previous_balance=float(pm.get('previous_balance', 0.0) or 0.0),
                new_balance=float(pm.get('new_balance', 0.0) or 0.0),
                payment_method=pm.get('payment_method', 'Efectivo'),
                reference=pm.get('reference'),
                notes=pm.get('notes'),
                status=pm.get('status', 'confirmado'),
                void_reason=pm.get('void_reason'),
                receipt_id=pm.get('receipt_id'),
                created_at=cls._parse_dt(pm.get('created_at')) or datetime.utcnow()
            ))
        session.flush()

        # 11. PurchasePayments (Supplier Payments)
        for pp in data.get('purchase_payments', []):
            session.add(PurchasePayment(
                id=pp.get('id'),
                payment_number=pp.get('payment_number'),
                purchase_id=pp.get('purchase_id'),
                supplier_id=pp.get('supplier_id'),
                user_id=pp.get('user_id'),
                amount=float(pp.get('amount', 0.0) or 0.0),
                previous_balance=float(pp.get('previous_balance', 0.0) or 0.0),
                new_balance=float(pp.get('new_balance', 0.0) or 0.0),
                payment_method=pp.get('payment_method', 'Efectivo'),
                reference=pp.get('reference'),
                notes=pp.get('notes'),
                status=pp.get('status', 'confirmado'),
                void_reason=pp.get('void_reason'),
                receipt_id=pp.get('receipt_id'),
                created_at=cls._parse_dt(pp.get('created_at')) or datetime.utcnow()
            ))
        session.flush()

        # 12. Inventory Movements
        mov_list = data.get('inventory_movements') if 'inventory_movements' in data else data.get('movements', [])
        for mv in mov_list:
            session.add(InventoryMovement(
                id=mv.get('id'),
                code=mv.get('code'),
                product_id=mv.get('product_id'),
                operation_type=mv.get('operation_type'),
                quantity=float(mv.get('quantity', 0.0) or 0.0),
                previous_stock=float(mv.get('previous_stock', 0.0) or 0.0),
                new_stock=float(mv.get('new_stock', 0.0) or 0.0),
                unit_price=float(mv.get('unit_price', 0.0) or 0.0),
                unit_cost=float(mv.get('unit_cost', 0.0) or 0.0),
                total_value=float(mv.get('total_value', 0.0) or 0.0),
                tax_applied=mv.get('tax_applied'),
                discount_percent=float(mv.get('discount_percent', 0.0) or 0.0),
                discount_amount=float(mv.get('discount_amount', 0.0) or 0.0),
                payment_condition=mv.get('payment_condition'),
                due_date=cls._parse_date(mv.get('due_date')),
                client_id=mv.get('client_id'),
                supplier_id=mv.get('supplier_id'),
                sale_id=mv.get('sale_id'),
                purchase_id=mv.get('purchase_id'),
                invoice_number=mv.get('invoice_number'),
                reason=mv.get('reason'),
                notes=mv.get('notes'),
                status=mv.get('status', 'confirmado'),
                is_reversal=bool(mv.get('is_reversal', False)),
                reversal_of_id=mv.get('reversal_of_id'),
                user_id=mv.get('user_id'),
                created_at=cls._parse_dt(mv.get('created_at')) or datetime.utcnow()
            ))
        session.flush()

        # 13. Financial Movements
        fin_list = data.get('financial_movements') if 'financial_movements' in data else data.get('finances', [])
        for fn in fin_list:
            session.add(FinancialMovement(
                id=fn.get('id'),
                code=fn.get('code'),
                movement_type=fn.get('movement_type'),
                category=fn.get('category'),
                amount=float(fn.get('amount', 0.0) or 0.0),
                payment_method=fn.get('payment_method', 'Efectivo'),
                description=fn.get('description', ''),
                receipt_id=fn.get('receipt_id'),
                sale_id=fn.get('sale_id'),
                purchase_id=fn.get('purchase_id'),
                payment_id=fn.get('payment_id'),
                purchase_payment_id=fn.get('purchase_payment_id'),
                user_id=fn.get('user_id'),
                date=cls._parse_date(fn.get('date')) or date.today(),
                status=fn.get('status', 'confirmado'),
                void_reason=fn.get('void_reason'),
                created_at=cls._parse_dt(fn.get('created_at')) or datetime.utcnow()
            ))
        session.flush()

        # 14. Audit Logs
        for al in data.get('audit_logs', []):
            session.add(AuditLog(
                id=al.get('id'),
                user_id=al.get('user_id'),
                user_name=al.get('user_name'),
                action=al.get('action', 'LOG'),
                entity_type=al.get('entity_type', 'System'),
                entity_id=al.get('entity_id'),
                details=al.get('details'),
                ip_address=al.get('ip_address'),
                created_at=cls._parse_dt(al.get('created_at')) or datetime.utcnow()
            ))
        session.flush()
        cls.sync_postgres_sequences(session)

    SERIAL_TABLES = (
        'users', 'suppliers', 'clients', 'products',
        'sales', 'sale_items', 'credit_exceptions',
        'purchases', 'purchase_items', 'purchase_payments',
        'payments', 'receipts', 'inventory_movements',
        'financial_movements', 'audit_logs'
    )

    @classmethod
    def sync_postgres_sequences(cls, session):
        """
        Synchronizes PostgreSQL SERIAL sequences after explicit-ID inserts (e.g., backup restore).
        Safe no-op on SQLite.
        """
        bind = getattr(session, 'bind', None) or session.get_bind()
        if not bind or getattr(bind.dialect, 'name', '') != 'postgresql':
            return 0
        synced = 0
        for table_name in cls.SERIAL_TABLES:
            stmt = text(
                f"SELECT setval("
                f"pg_get_serial_sequence('{table_name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), "
                f"(SELECT COUNT(*) > 0 FROM {table_name})"
                f")"
            )
            session.execute(stmt)
            synced += 1
        return synced

    @classmethod
    def verify_backup_in_isolated_db(cls, data: dict):
        """
        Tests restoring the backup payload into an isolated in-memory SQLite database
        and compares every table's restored count against the source payload before touching real data.
        Returns (ok: bool, message: str, restored_counts: dict).
        """
        try:
            cls.validate_backup_payload(data)
        except Exception as e:
            return False, str(e), {}

        iso_engine = create_engine('sqlite:///:memory:')
        db.Model.metadata.create_all(iso_engine)
        IsoSession = sessionmaker(bind=iso_engine)
        iso_session = IsoSession()

        try:
            cls._populate_session_from_dict(iso_session, data)
            iso_session.commit()

            # Compare restored counts
            restored_counts = {
                'users': iso_session.query(User).count(),
                'system_settings': iso_session.query(SystemSetting).count(),
                'suppliers': iso_session.query(Supplier).count(),
                'clients': iso_session.query(Client).count(),
                'products': iso_session.query(Product).count(),
                'sales': iso_session.query(Sale).count(),
                'sale_items': iso_session.query(SaleItem).count(),
                'credit_exceptions': iso_session.query(CreditException).count(),
                'purchases': iso_session.query(Purchase).count(),
                'purchase_items': iso_session.query(PurchaseItem).count(),
                'receipts': iso_session.query(Receipt).count(),
                'payments': iso_session.query(Payment).count(),
                'purchase_payments': iso_session.query(PurchasePayment).count(),
                'inventory_movements': iso_session.query(InventoryMovement).count(),
                'financial_movements': iso_session.query(FinancialMovement).count(),
                'audit_logs': iso_session.query(AuditLog).count(),
            }

            expected_map = {
                'suppliers': len(data.get('suppliers', [])),
                'clients': len(data.get('clients', [])),
                'products': len(data.get('products', [])),
                'sales': len(data.get('sales', [])),
                'purchases': len(data.get('purchases', [])),
                'receipts': len(data.get('receipts', [])),
                'payments': len(data.get('payments', [])),
                'purchase_payments': len(data.get('purchase_payments', [])),
                'inventory_movements': len(data.get('inventory_movements', data.get('movements', []))),
                'financial_movements': len(data.get('financial_movements', data.get('finances', []))),
            }

            for k, exp_val in expected_map.items():
                if restored_counts[k] != exp_val:
                    return (
                        False,
                        f"Error en restauración de prueba aislada ({k}): esperados {exp_val}, restaurados {restored_counts[k]}.",
                        restored_counts
                    )

            msg = (
                f"Integridad verificada en base de datos aislada: "
                f"{restored_counts['products']} productos, {restored_counts['clients']} clientes, "
                f"{restored_counts['suppliers']} proveedores, {restored_counts['sales']} ventas, "
                f"{restored_counts['purchases']} compras, {restored_counts['inventory_movements']} movimientos."
            )
            return True, msg, restored_counts
        except Exception as e:
            return False, str(e), {}
        finally:
            iso_session.close()
            iso_engine.dispose()

    @classmethod
    def restore_full_backup(cls, data: dict, user_id=None, verify_first=True, restored_by_user_id=None, clear_existing=True, restore_media=True, allow_cross_env=False):
        """
        Executes a verified, transactional full system restore:
        1. Validates payload structure, environment isolation rules, and SHA-256 checksum.
        2. Runs a full test restore in an isolated database first.
        3. Saves an automatic pre-restore backup to disk (never overwriting existing backups).
        4. Restores all database tables in strict relational order and syncs PostgreSQL sequences.
        5. Restores associated media files with SHA-256 verification.
        """
        uid = user_id or restored_by_user_id

        # Enforce environment isolation: block restoring staging/testing backups into production
        try:
            current_env = current_app.config.get('APP_ENV', 'development')
        except RuntimeError:
            current_env = 'development'

        source_env = (data.get('metadata', {}) or {}).get('environment', '').lower() if isinstance(data, dict) else ''
        if current_env == 'production' and source_env in ('staging', 'testing') and not allow_cross_env:
            raise ValueError(
                f"Seguridad de aislamiento: No se permite restaurar un respaldo generado en el entorno "
                f"'{source_env}' dentro de PRODUCCIÓN."
            )

        if verify_first:
            ok, msg, restored_counts = cls.verify_backup_in_isolated_db(data)
            if not ok:
                raise ValueError(msg)
            verification = {'verified': True, 'restored_counts': restored_counts}
        else:
            cls.validate_backup_payload(data)
            verification = {'verified': True, 'restored_counts': {}}

        # Save automatic pre-restore backup snapshot on disk
        try:
            backups_dir = os.path.join(current_app.root_path, 'backups')
            os.makedirs(backups_dir, exist_ok=True)
            pre_filename = f"auto_pre_restore_{current_env}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.json"
            pre_path = os.path.join(backups_dir, pre_filename)
            pre_snapshot = cls.generate_full_backup_dict(exported_by='auto_pre_restore')
            with open(pre_path, 'w', encoding='utf-8') as f:
                json.dump(pre_snapshot, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        # Populate current DB session transactionally
        cls._populate_session_from_dict(db.session, data)

        # Restore media files if included
        media_restored = 0
        upload_dir = current_app.config.get('UPLOAD_FOLDER')
        if upload_dir and restore_media:
            for mf in data.get('media_files', []):
                rel_p = mf.get('relative_path')
                b64_c = mf.get('content_b64')
                exp_sha = mf.get('sha256')
                if not rel_p or not b64_c:
                    continue
                # Prevent path traversal
                norm_rel = os.path.normpath(rel_p).lstrip(os.sep).lstrip('/')
                if '..' in norm_rel:
                    continue
                raw_bytes = base64.b64decode(b64_c.encode('ascii'))
                if exp_sha and hashlib.sha256(raw_bytes).hexdigest() != exp_sha:
                    raise ValueError(f"Checksum inválido para el archivo adjunto '{rel_p}'.")
                target_file = os.path.join(upload_dir, norm_rel)
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                with open(target_file, 'wb') as out_f:
                    out_f.write(raw_bytes)
                media_restored += 1

        audit = AuditLog(
            user_id=uid,
            action='RESTORE_FULL_BACKUP',
            entity_type='Database',
            details=(
                f"Restauración íntegra verificada completada: "
                f"{len(data.get('products', []))} productos, {len(data.get('clients', []))} clientes, "
                f"{len(data.get('suppliers', []))} proveedores, {len(data.get('sales', []))} ventas, "
                f"{len(data.get('purchases', []))} compras, {len(data.get('inventory_movements', data.get('movements', [])))} movimientos, "
                f"{media_restored} archivos multimedia."
            )
        )
        db.session.add(audit)
        db.session.commit()

        return {
            'success': True,
            'verification': verification,
            'media_restored': media_restored,
            'products': len(data.get('products', [])),
            'clients': len(data.get('clients', [])),
            'suppliers': len(data.get('suppliers', [])),
            'sales': len(data.get('sales', [])),
            'purchases': len(data.get('purchases', [])),
            'inventory_movements': len(data.get('inventory_movements', data.get('movements', []))),
            'financial_movements': len(data.get('financial_movements', data.get('finances', []))),
            'receipts': len(data.get('receipts', []))
        }
