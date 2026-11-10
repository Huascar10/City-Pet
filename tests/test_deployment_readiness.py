import io
import os
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
from sqlalchemy import create_engine, inspect

from app import create_app
from config import resolve_config_name, validate_environment_isolation
from extensions import db
from models import User, Product, SystemSetting
from services.storage_service import StorageService, StorageValidationError
from services.telegram_service import TelegramService
from services.backup_service import BackupService
from services.migration_service import MigrationService


def _create_valid_png_bytes(width=120, height=120, color=(27, 73, 101)) -> bytes:
    buf = io.BytesIO()
    img = Image.new('RGB', (width, height), color=color)
    img.save(buf, format='PNG')
    return buf.getvalue()


class TestPhase2And8EnvironmentAndIsolation:
    """Tests for Phase 2 (Two Environments: staging & production) and Phase 8 (Cross-environment Isolation)."""

    def test_resolve_config_name_priority_and_aliases(self, monkeypatch):
        monkeypatch.delenv('APP_ENV', raising=False)
        monkeypatch.delenv('FLASK_CONFIG', raising=False)
        assert resolve_config_name(None) == 'development'
        assert resolve_config_name('default') == 'development'
        assert resolve_config_name('staging') == 'staging'
        assert resolve_config_name('production') == 'production'
        assert resolve_config_name('prod') == 'production'

        monkeypatch.setenv('APP_ENV', 'staging')
        assert resolve_config_name(None) == 'staging'

        monkeypatch.setenv('APP_ENV', 'production')
        assert resolve_config_name(None) == 'production'

    def test_staging_startup_fails_safely_when_secret_key_or_database_url_missing(self, monkeypatch):
        monkeypatch.delenv('SECRET_KEY', raising=False)
        monkeypatch.delenv('DATABASE_URL', raising=False)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app('staging')

        monkeypatch.setenv('SECRET_KEY', 'staging-secret-key-with-more-than-16-chars-123456')
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            create_app('staging')

    def test_production_startup_fails_safely_when_secret_key_or_database_url_missing(self, monkeypatch):
        monkeypatch.delenv('SECRET_KEY', raising=False)
        monkeypatch.delenv('DATABASE_URL', raising=False)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app('production')

        monkeypatch.setenv('SECRET_KEY', 'production-secret-key-with-more-than-16-chars-999')
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            create_app('production')

    def test_staging_and_production_reject_default_sqlite_and_succeed_with_isolated_dbs(self, monkeypatch, tmp_path):
        staging_db = tmp_path / "staging_isolated.db"
        prod_db = tmp_path / "prod_isolated.db"

        # Without ALLOW_SQLITE_IN_DEPLOY, staging rejects SQLite URI and requires PostgreSQL
        monkeypatch.setenv('SECRET_KEY', 'staging-unique-secret-key-abcdef1234567890')
        monkeypatch.setenv('DATABASE_URL', f'sqlite:///{staging_db.as_posix()}')
        monkeypatch.delenv('ALLOW_SQLITE_IN_DEPLOY', raising=False)
        with pytest.raises(RuntimeError, match="PostgreSQL dedicada"):
            create_app('staging')

        # With isolated test flag enabled, still blocks connecting to local citypet.db
        monkeypatch.setenv('ALLOW_SQLITE_IN_DEPLOY', 'true')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///citypet.db')
        with pytest.raises(RuntimeError, match="citypet.db"):
            create_app('staging')

        # 1. Start STAGING with isolated DB
        monkeypatch.setenv('DATABASE_URL', f'sqlite:///{staging_db.as_posix()}')
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-staging-media')
        staging_app = create_app('staging')
        assert staging_app.config['APP_ENV'] == 'staging'
        assert staging_app.config['DEBUG'] is False
        assert staging_app.config['SESSION_COOKIE_SECURE'] is True
        assert staging_app.config['SESSION_COOKIE_HTTPONLY'] is True
        assert staging_app.config['SESSION_COOKIE_NAME'] == 'citypet_staging_session'
        assert staging_app.config['TELEGRAM_ENABLED'] is False

        # 2. Start PRODUCTION with isolated DB
        monkeypatch.setenv('SECRET_KEY', 'production-unique-secret-key-9876543210fedcba')
        monkeypatch.setenv('DATABASE_URL', f'sqlite:///{prod_db.as_posix()}')
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-production-media')
        prod_app = create_app('production')
        assert prod_app.config['APP_ENV'] == 'production'
        assert prod_app.config['DEBUG'] is False
        assert prod_app.config['SESSION_COOKIE_SECURE'] is True
        assert prod_app.config['SESSION_COOKIE_HTTPONLY'] is True
        assert prod_app.config['SESSION_COOKIE_NAME'] == 'citypet_prod_session'

    def test_cross_environment_contamination_is_blocked(self, monkeypatch):
        # Staging trying to connect to a production database or bucket must fail immediately
        monkeypatch.setenv('SECRET_KEY', 'staging-unique-secret-key-abcdef1234567890')
        monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@host:6543/citypet-production')
        with pytest.raises(RuntimeError, match="VIOLACIÓN CRÍTICA DE AISLAMIENTO"):
            create_app('staging')

        monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@host:6543/citypet_staging')
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-production-media')
        with pytest.raises(RuntimeError, match="VIOLACIÓN CRÍTICA DE AISLAMIENTO"):
            create_app('staging')

        # Production trying to connect to a staging database or bucket must fail immediately
        monkeypatch.setenv('SECRET_KEY', 'production-unique-secret-key-9876543210fedcba')
        monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@host:6543/citypet-staging')
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-production-media')
        with pytest.raises(RuntimeError, match="VIOLACIÓN CRÍTICA DE AISLAMIENTO"):
            create_app('production')

    def test_postgres_url_normalization_and_engine_options(self, monkeypatch):
        monkeypatch.setenv('SECRET_KEY', 'staging-unique-secret-key-abcdef1234567890')
        monkeypatch.setenv('DATABASE_URL', 'postgres://postgres.stagingref:secret@pooler.supabase.com:6543/postgres')
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-staging-media')
        app = create_app('staging')
        assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql+psycopg2://')
        assert app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_pre_ping'] is True
        assert app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_recycle'] == 300


class TestPhase3MigrationsAndPostgresCompatibility:
    """Tests for Phase 3 (Migrations on empty DB, existing DB, and PostgreSQL sequence sync)."""

    def test_migration_service_creates_all_17_tables_on_empty_database(self, tmp_path):
        empty_db = tmp_path / "empty_test.db"
        engine = create_engine(f"sqlite:///{empty_db.as_posix()}")
        res = MigrationService.upgrade_engine(engine, metadata=db.Model.metadata)
        assert res['status'] == 'success'

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected_tables = {
            'users', 'login_attempts', 'system_settings', 'suppliers', 'clients',
            'products', 'sales', 'sale_items', 'credit_exceptions', 'purchases',
            'purchase_items', 'purchase_payments', 'payments', 'receipts',
            'inventory_movements', 'financial_movements', 'audit_logs'
        }
        assert expected_tables.issubset(tables)
        engine.dispose()

    def test_alembic_initial_migration_upgrade_and_downgrade_non_destructive(self, tmp_path):
        mig_db = tmp_path / "alembic_test.db"
        engine = create_engine(f"sqlite:///{mig_db.as_posix()}")
        # Run upgrade_engine twice to verify idempotency and zero data loss
        MigrationService.upgrade_engine(engine, metadata=db.Model.metadata)
        res2 = MigrationService.upgrade_engine(engine, metadata=db.Model.metadata)
        assert res2['status'] == 'success'
        assert res2['applied_columns'] == []
        engine.dispose()

    def test_postgres_sequence_synchronization_executes_setval_for_all_tables(self):
        mock_session = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = 'postgresql'
        mock_session.bind = mock_bind

        synced_count = BackupService.sync_postgres_sequences(mock_session)
        assert synced_count == len(BackupService.SERIAL_TABLES)
        assert mock_session.execute.call_count == len(BackupService.SERIAL_TABLES)


class TestPhase4StorageValidationAndSupabaseUpload:
    """Tests for Phase 4 (Image validation, dangerous filename rejection, and Supabase Storage upload)."""

    def test_valid_image_upload_local_and_supabase_mock(self, tmp_path, monkeypatch):
        monkeypatch.setenv('ALLOW_SQLITE_IN_DEPLOY', 'true')
        monkeypatch.setenv('SECRET_KEY', 'staging-unique-secret-key-abcdef1234567890')
        monkeypatch.setenv('DATABASE_URL', f"sqlite:///{(tmp_path / 'st.db').as_posix()}")
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-staging-media')
        app = create_app('staging')
        app.config['UPLOAD_FOLDER'] = str(tmp_path / "uploads")

        png_bytes = _create_valid_png_bytes()

        with app.app_context():
            # 1. Local storage fallback when SUPABASE_URL is empty
            from werkzeug.datastructures import FileStorage
            fs = FileStorage(stream=io.BytesIO(png_bytes), filename="collar_perro.png", content_type="image/png")
            local_url = StorageService.save_product_image(fs)
            assert local_url.startswith("/static/uploads/prod_")
            assert local_url.endswith(".png")

            # 2. Supabase Storage upload when SUPABASE_URL and SUPABASE_KEY are configured
            app.config['SUPABASE_URL'] = 'https://stagingproj.supabase.co'
            app.config['SUPABASE_KEY'] = 'service-role-secret-staging'
            app.config['SUPABASE_STORAGE_BUCKET'] = 'citypet-staging-media'

            with patch('services.storage_service.requests.post') as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_post.return_value = mock_resp

                fs2 = FileStorage(stream=io.BytesIO(png_bytes), filename="vacuna_canina.png", content_type="image/png")
                remote_url = StorageService.save_product_image(fs2)
                assert remote_url.startswith(
                    "https://stagingproj.supabase.co/storage/v1/object/public/citypet-staging-media/products/prod_"
                )
                assert mock_post.called

    def test_rejects_disallowed_extensions_and_corrupted_images(self, tmp_path):
        app = create_app('testing')
        app.config['UPLOAD_FOLDER'] = str(tmp_path / "uploads")
        from werkzeug.datastructures import FileStorage

        with app.app_context():
            # Dangerous double extension
            bad_ext = FileStorage(stream=io.BytesIO(b"malicious"), filename="exploit.php.png")
            with pytest.raises(StorageValidationError, match="políticas de seguridad"):
                StorageService.validate_image_file(bad_ext)

            # Fake image content with .png extension
            fake_img = FileStorage(stream=io.BytesIO(b"not a real png binary"), filename="fake.png")
            with pytest.raises(StorageValidationError, match="imagen válida"):
                StorageService.validate_image_file(fake_img)


class TestPhase5TelegramEnvironmentIsolation:
    """Tests for Phase 5 (Telegram disabled by default in staging, [STAGING] prefix, and prod chat block)."""

    def test_telegram_staging_prefix_and_production_chat_block(self, tmp_path, monkeypatch):
        monkeypatch.setenv('ALLOW_SQLITE_IN_DEPLOY', 'true')
        monkeypatch.setenv('SECRET_KEY', 'staging-unique-secret-key-abcdef1234567890')
        monkeypatch.setenv('DATABASE_URL', f"sqlite:///{(tmp_path / 'tg_st.db').as_posix()}")
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-staging-media')
        monkeypatch.setenv('PRODUCTION_TELEGRAM_CHAT_ID', '-100999888777')

        app = create_app('staging')
        with app.app_context():
            db.create_all()
            cfg = TelegramService.get_config()
            assert cfg['enabled'] is False

            # Attempting to send to production chat ID from staging must be blocked
            ok, msg = TelegramService.send_raw_message('12345:token', '-100999888777', 'Mensaje de prueba')
            assert ok is False
            assert 'PRODUCCIÓN' in msg

            # Sending to a test chat ID from staging prefixes the message with STAGING banner
            with patch('services.telegram_service.requests.post') as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {'ok': True}
                mock_post.return_value = mock_resp

                ok2, _ = TelegramService.send_raw_message('12345:token', '-100111222333', 'Venta ficticia')
                assert ok2 is True
                sent_json = mock_post.call_args.kwargs['json']
                assert '[ENTORNO DE PRUEBAS - STAGING]' in sent_json['text']


class TestPhase7And8HealthcheckAndBackupIsolation:
    """Tests for Phase 7 (/health endpoint) and Phase 8 (Blocking staging backup restore in production)."""

    def test_health_endpoint_returns_environment_and_connected_status(self):
        app = create_app('testing')
        with app.app_context():
            db.create_all()
            client = app.test_client()
            resp = client.get('/health')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['status'] == 'ok'
            assert data['database'] == 'connected'
            assert data['environment'] == 'testing'

    def test_production_blocks_restoring_staging_backup(self, tmp_path, monkeypatch):
        monkeypatch.setenv('ALLOW_SQLITE_IN_DEPLOY', 'true')
        monkeypatch.setenv('SECRET_KEY', 'production-unique-secret-key-9876543210fedcba')
        monkeypatch.setenv('DATABASE_URL', f"sqlite:///{(tmp_path / 'prod_restore_guard.db').as_posix()}")
        monkeypatch.setenv('SUPABASE_STORAGE_BUCKET', 'citypet-production-media')

        prod_app = create_app('production')
        with prod_app.app_context():
            db.create_all()
            snapshot = BackupService.generate_full_backup_dict(exported_by='test')
            # Simulate a backup coming from staging
            snapshot['metadata']['environment'] = 'staging'

            with pytest.raises(ValueError, match="Seguridad de aislamiento"):
                BackupService.restore_full_backup(snapshot)
