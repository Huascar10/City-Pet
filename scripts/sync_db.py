import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from extensions import db
from services.migration_service import MigrationService


def run_sync():
    """
    Synchronizes database schema non-destructively across SQLite or PostgreSQL (Supabase).
    Creates missing tables and adds any missing columns while preserving 100% of existing data.
    """
    app = create_app()
    with app.app_context():
        result = MigrationService.upgrade_engine(db.engine, metadata=db.Model.metadata)
        print(
            f"Database migration and sync completed successfully "
            f"(dialect={result['dialect']}, applied_columns={len(result['applied_columns'])})."
        )
        for col in result['applied_columns']:
            print(f" + Added column: {col}")


if __name__ == '__main__':
    run_sync()
