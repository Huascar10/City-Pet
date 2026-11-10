"""Initial CityPet complete schema and non-destructive column synchronization

Revision ID: 0001_initial_citypet_schema
Revises: None
Create Date: 2026-04-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from models import db
from services.migration_service import MigrationService

# revision identifiers, used by Alembic.
revision = '0001_initial_citypet_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """
    Idempotently creates all 17 CityPet tables on an empty database (PostgreSQL or SQLite)
    and non-destructively adds any missing columns on an existing database without losing records.
    """
    bind = op.get_bind()
    db.Model.metadata.create_all(bind=bind)
    MigrationService.upgrade_engine(bind, metadata=None)


def downgrade():
    """
    Non-destructive downgrade guard: never drops tables containing commercial data automatically.
    """
    pass
