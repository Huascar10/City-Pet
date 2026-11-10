import sqlite3
import os
from datetime import datetime
from sqlalchemy import inspect, text


class MigrationService:
    """
    Reversible, non-destructive schema migration manager for CityPet
    supporting both PostgreSQL (Supabase) and SQLite databases.
    Preserves 100% of existing records and relationships.
    """
    NEW_COLUMNS = [
        ('users', 'can_authorize_credit', 'BOOLEAN NOT NULL DEFAULT TRUE', 'BOOLEAN NOT NULL DEFAULT 1'),
        ('users', 'failed_login_attempts', 'INTEGER NOT NULL DEFAULT 0', 'INTEGER NOT NULL DEFAULT 0'),
        ('users', 'locked_until', 'TIMESTAMP NULL', 'DATETIME NULL'),
        ('sales', 'paid_amount', 'DOUBLE PRECISION NOT NULL DEFAULT 0.0', 'FLOAT NOT NULL DEFAULT 0.0'),
        ('sales', 'idempotency_token', 'VARCHAR(100) NULL', 'VARCHAR(100) NULL'),
        ('sales', 'void_reason', 'VARCHAR(255) NULL', 'VARCHAR(255) NULL'),
        ('sales', 'voided_by_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('sales', 'voided_at', 'TIMESTAMP NULL', 'DATETIME NULL'),
        ('sales', 'due_date', 'DATE NULL', 'DATE NULL'),
        ('sales', 'credit_exception_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('purchases', 'paid_amount', 'DOUBLE PRECISION NOT NULL DEFAULT 0.0', 'FLOAT NOT NULL DEFAULT 0.0'),
        ('purchases', 'due_date', 'DATE NULL', 'DATE NULL'),
        ('inventory_movements', 'purchase_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('inventory_movements', 'status', "VARCHAR(20) DEFAULT 'confirmado'", "VARCHAR(20) DEFAULT 'confirmado'"),
        ('inventory_movements', 'void_reason', 'VARCHAR(255) NULL', 'VARCHAR(255) NULL'),
        ('inventory_movements', 'voided_by_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('inventory_movements', 'voided_at', 'TIMESTAMP NULL', 'DATETIME NULL'),
        ('inventory_movements', 'tax_applied', 'VARCHAR(20) NULL', 'VARCHAR(20) NULL'),
        ('inventory_movements', 'discount_percent', 'DOUBLE PRECISION DEFAULT 0.0', 'FLOAT DEFAULT 0.0'),
        ('inventory_movements', 'discount_amount', 'DOUBLE PRECISION DEFAULT 0.0', 'FLOAT DEFAULT 0.0'),
        ('inventory_movements', 'payment_condition', 'VARCHAR(50) NULL', 'VARCHAR(50) NULL'),
        ('inventory_movements', 'due_date', 'DATE NULL', 'DATE NULL'),
        ('financial_movements', 'purchase_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('financial_movements', 'payment_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('financial_movements', 'purchase_payment_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('financial_movements', 'status', "VARCHAR(20) DEFAULT 'confirmado'", "VARCHAR(20) DEFAULT 'confirmado'"),
        ('financial_movements', 'void_reason', 'VARCHAR(255) NULL', 'VARCHAR(255) NULL'),
        ('financial_movements', 'voided_by_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('financial_movements', 'voided_at', 'TIMESTAMP NULL', 'DATETIME NULL'),
        ('receipts', 'related_purchase_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('receipts', 'related_payment_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('receipts', 'related_purchase_payment_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('receipts', 'void_reason', 'VARCHAR(255) NULL', 'VARCHAR(255) NULL'),
        ('receipts', 'voided_by_id', 'INTEGER NULL', 'INTEGER NULL'),
        ('receipts', 'voided_at', 'TIMESTAMP NULL', 'DATETIME NULL'),
    ]

    NEW_TABLES_SQL = [
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            ip_address VARCHAR(64) NOT NULL,
            username VARCHAR(100),
            success BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_login_attempts_ip_address ON login_attempts (ip_address);",
        "CREATE INDEX IF NOT EXISTS ix_login_attempts_username ON login_attempts (username);",
        "CREATE INDEX IF NOT EXISTS ix_login_attempts_created_at ON login_attempts (created_at);",
        """
        CREATE TABLE IF NOT EXISTS credit_exceptions (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER REFERENCES sales(id) ON DELETE CASCADE,
            client_id INTEGER NOT NULL REFERENCES clients(id),
            authorized_by_id INTEGER NOT NULL REFERENCES users(id),
            authorized_by_username VARCHAR(50) NOT NULL,
            requested_by_id INTEGER REFERENCES users(id),
            reason TEXT NOT NULL,
            credit_limit_snapshot FLOAT NOT NULL DEFAULT 0.0,
            previous_debt_snapshot FLOAT NOT NULL DEFAULT 0.0,
            new_credit_amount FLOAT NOT NULL DEFAULT 0.0,
            excess_amount FLOAT NOT NULL DEFAULT 0.0,
            had_overdue_invoices BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_credit_exceptions_sale_id ON credit_exceptions (sale_id);",
        "CREATE INDEX IF NOT EXISTS ix_credit_exceptions_client_id ON credit_exceptions (client_id);",
        "CREATE INDEX IF NOT EXISTS ix_credit_exceptions_created_at ON credit_exceptions (created_at);",
        """
        CREATE TABLE IF NOT EXISTS purchase_payments (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            payment_number VARCHAR(50) NOT NULL UNIQUE,
            purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
            user_id INTEGER REFERENCES users(id),
            amount FLOAT NOT NULL,
            previous_balance FLOAT NOT NULL,
            new_balance FLOAT NOT NULL,
            payment_method VARCHAR(50) DEFAULT 'Efectivo',
            reference VARCHAR(100),
            notes TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'confirmado',
            void_reason VARCHAR(255),
            voided_by_id INTEGER REFERENCES users(id),
            voided_at DATETIME,
            receipt_id INTEGER REFERENCES receipts(id),
            idempotency_token VARCHAR(100) UNIQUE,
            created_at DATETIME
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_purchase_payments_payment_number ON purchase_payments (payment_number);",
        "CREATE INDEX IF NOT EXISTS ix_purchase_payments_purchase_id ON purchase_payments (purchase_id);",
        "CREATE INDEX IF NOT EXISTS ix_purchase_payments_supplier_id ON purchase_payments (supplier_id);",
        "CREATE INDEX IF NOT EXISTS ix_purchase_payments_created_at ON purchase_payments (created_at);",
    ]

    @classmethod
    def upgrade_engine(cls, engine, metadata=None):
        """
        Non-destructively upgrades any SQLAlchemy engine (PostgreSQL or SQLite):
        1. Creates any missing tables via metadata.create_all(bind=engine) if metadata is provided.
        2. Adds any missing columns idempotently without dropping tables or losing data.
        3. Runs safe data normalization updates.
        """
        if metadata is not None:
            metadata.create_all(bind=engine)

        dialect = engine.dialect.name
        is_pg = (dialect == 'postgresql')
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        applied_columns = []

        with engine.begin() as conn:
            for item in cls.NEW_COLUMNS:
                table, col, pg_def, sqlite_def = item
                if table not in existing_tables:
                    continue
                existing_cols = {c['name'] for c in inspector.get_columns(table)}
                if col not in existing_cols:
                    col_def = pg_def if is_pg else sqlite_def
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                    applied_columns.append(f"{table}.{col}")

            if 'users' in existing_tables:
                false_lit = 'FALSE' if is_pg else '0'
                conn.execute(text(f"UPDATE users SET can_authorize_credit = {false_lit} WHERE role = 'empleado'"))

            if 'purchases' in existing_tables:
                conn.execute(text(
                    "UPDATE purchases SET paid_amount = total "
                    "WHERE paid_amount = 0 AND LOWER(payment_condition) NOT LIKE '%credito%' "
                    "AND LOWER(payment_condition) NOT LIKE '%crédito%'"
                ))

            if 'sales' in existing_tables:
                conn.execute(text(
                    "UPDATE sales SET paid_amount = total "
                    "WHERE payment_condition = 'Contado' AND (paid_amount IS NULL OR paid_amount = 0)"
                ))

        return {'status': 'success', 'dialect': dialect, 'applied_columns': applied_columns}

    @classmethod
    def upgrade(cls, db_path='citypet.db'):
        if not os.path.exists(db_path):
            return {'status': 'skipped', 'reason': 'db_not_found'}

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        applied_columns = []
        try:
            # 1. Create new tables & indexes
            for sql in cls.NEW_TABLES_SQL:
                cur.execute(sql)

            # 2. Add missing columns idempotently
            for table, col, _pg_def, sqlite_def in cls.NEW_COLUMNS:
                existing_cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
                if existing_cols and col not in existing_cols:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sqlite_def}")
                    applied_columns.append(f"{table}.{col}")

            # 3. Ensure employee users have can_authorize_credit = 0 by default
            cur.execute("UPDATE users SET can_authorize_credit = 0 WHERE role = 'empleado'")
            # 4. Ensure existing non-credit purchases have paid_amount = total
            cur.execute(
                "UPDATE purchases SET paid_amount = total "
                "WHERE paid_amount = 0 AND LOWER(payment_condition) NOT LIKE '%credito%' AND LOWER(payment_condition) NOT LIKE '%crédito%'"
            )

            conn.commit()
            return {'status': 'success', 'applied_columns': applied_columns}
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    @classmethod
    def downgrade_from_backup(cls, backup_path='backups/citypet_pre_transformation_backup.db', target_path='citypet.db'):
        """Reversible rollback procedure restoring the verified pre-migration snapshot."""
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup no encontrado: {backup_path}")
        src = sqlite3.connect(backup_path)
        dst = sqlite3.connect(target_path)
        src.backup(dst)
        dst.close()
        src.close()
        return {'status': 'rolled_back', 'from': backup_path}
