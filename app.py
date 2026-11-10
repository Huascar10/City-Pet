import os
import click
from datetime import datetime
from flask import Flask, jsonify, render_template
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
from config import config, resolve_config_name, apply_runtime_environment_overrides
from extensions import db, migrate, login_manager, csrf


def create_app(config_name=None):
    resolved_name = resolve_config_name(config_name)

    app = Flask(__name__)
    app.config.from_object(config[resolved_name])
    apply_runtime_environment_overrides(app, resolved_name)

    # Respect HTTPS & client IP headers behind Render / reverse proxies
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Ensure local upload fallback directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register blueprints
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.products import products_bp
    from routes.inventory import inventory_bp
    from routes.sales import sales_bp
    from routes.purchases import purchases_bp
    from routes.clients import clients_bp
    from routes.suppliers import suppliers_bp
    from routes.finances import finances_bp
    from routes.receipts import receipts_bp
    from routes.imports import imports_bp
    from routes.reports import reports_bp
    from routes.settings import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(finances_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        if app.config.get('APP_ENV') in ('staging', 'production'):
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        return response

    @app.route('/health', methods=['GET'])
    def healthcheck():
        """Render health check endpoint verifying database connectivity without exposing secrets."""
        from services.storage_service import StorageService
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify({
                'status': 'ok',
                'environment': app.config.get('APP_ENV', 'development'),
                'database': 'connected',
                'storage_backend': 'supabase' if StorageService.is_supabase_configured() else 'local'
            }), 200
        except Exception:
            db.session.rollback()
            return jsonify({
                'status': 'error',
                'environment': app.config.get('APP_ENV', 'development'),
                'database': 'disconnected'
            }), 503

    # Context processors
    @app.context_processor
    def inject_global_vars():
        from models import SystemSetting
        comp_name = SystemSetting.get_val('company_name', app.config.get('COMPANY_NAME'))
        comp_ruc = SystemSetting.get_val('company_ruc', app.config.get('COMPANY_RUC'))
        currency = SystemSetting.get_val('company_currency', app.config.get('COMPANY_CURRENCY', 'C$'))
        system_logo_url = SystemSetting.get_val('system_logo_url', '/static/img/citypet_logo.png')
        receipt_logo_url = SystemSetting.get_val('receipt_logo_url', '/static/img/citypet_logo_whitebg.png')
        theme_mode = SystemSetting.get_val('theme_mode', 'sistema')
        color_preset = SystemSetting.get_val('color_preset', 'veterinario')
        theme_primary_color = SystemSetting.get_val('theme_primary_color', '#1B4965')
        theme_secondary_color = SystemSetting.get_val('theme_secondary_color', '#62B6CB')
        app_env = app.config.get('APP_ENV', 'development')

        return dict(
            company_name=comp_name,
            company_ruc=comp_ruc,
            currency=currency,
            system_logo_url=system_logo_url,
            receipt_logo_url=receipt_logo_url,
            theme_mode=theme_mode,
            color_preset=color_preset,
            theme_primary_color=theme_primary_color,
            theme_secondary_color=theme_secondary_color,
            app_env=app_env,
            is_staging=(app_env == 'staging'),
            now=datetime.utcnow()
        )

    # Error handlers (never leak stack traces or sensitive strings)
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    # CLI commands
    @app.cli.command("init-db")
    def init_db():
        """Creates/synchronizes database tables non-destructively and ensures the owner user exists."""
        from services.migration_service import MigrationService
        from models import User
        with app.app_context():
            MigrationService.upgrade_engine(db.engine, metadata=db.Model.metadata)
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                initial_password = os.environ.get('ADMIN_INITIAL_PASSWORD', 'admin123')
                admin = User(
                    username='admin',
                    full_name='Propietario CityPet',
                    email='admin@citypet.com',
                    role='propietario',
                    is_active=True,
                    can_authorize_credit=True
                )
                admin.set_password(initial_password)
                db.session.add(admin)
                db.session.commit()
                click.echo("Base de datos inicializada. Usuario propietario 'admin' creado correctamente.")
            else:
                click.echo("La base de datos ya contiene al usuario 'admin'.")

    @app.cli.command("sync-schema")
    def sync_schema():
        """Synchronizes database schema and PostgreSQL sequences non-destructively."""
        from services.migration_service import MigrationService
        from services.backup_service import BackupService
        with app.app_context():
            res = MigrationService.upgrade_engine(db.engine, metadata=db.Model.metadata)
            seq_count = BackupService.sync_postgres_sequences(db.session)
            db.session.commit()
            click.echo(
                f"Esquema sincronizado ({res['dialect']}): "
                f"{len(res['applied_columns'])} columna(s) nueva(s), "
                f"{seq_count} secuencia(s) PostgreSQL verificada(s)."
            )

    @app.cli.command("migrate-media")
    def migrate_media():
        """Migrates local images in static/uploads/ to Supabase Storage."""
        from services.storage_service import StorageService
        with app.app_context():
            report = StorageService.migrate_local_media_to_supabase()
            click.echo(
                f"Migración de medios completada: "
                f"Productos migrados={report['migrated_products']}, "
                f"Logos migrados={report['migrated_settings']}, "
                f"Omitidos={report['skipped']}, "
                f"Errores={len(report['errors'])}"
            )
            for err in report['errors']:
                click.echo(f" ! {err}")

    @app.cli.command("seed-excel")
    def seed_excel():
        """Imports the master Excel database (INVENTARIO NUEVO.xlsx)."""
        if app.config.get('APP_ENV') == 'production' and os.environ.get('ALLOW_PRODUCTION_SEED') != 'true':
            click.echo("Operación bloqueada: 'seed-excel' está deshabilitado en PRODUCTION por seguridad.")
            return

        from services.excel_service import ExcelService
        from services.migration_service import MigrationService
        from models import User
        excel_path = os.path.join(app.root_path, 'INVENTARIO NUEVO.xlsx')
        if not os.path.exists(excel_path):
            click.echo(f"Error: {excel_path} no encontrado.")
            return

        with app.app_context():
            MigrationService.upgrade_engine(db.engine, metadata=db.Model.metadata)
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                initial_password = os.environ.get('ADMIN_INITIAL_PASSWORD', 'admin123')
                admin = User(
                    username='admin',
                    full_name='Propietario CityPet',
                    email='admin@citypet.com',
                    role='propietario',
                    is_active=True,
                    can_authorize_credit=True
                )
                admin.set_password(initial_password)
                db.session.add(admin)
                db.session.commit()

            click.echo("Iniciando importación desde INVENTARIO NUEVO.xlsx...")
            report = ExcelService.import_citypet_master_excel(excel_path, admin.id)
            click.echo(
                f"Importación finalizada con éxito:\n"
                f"- Proveedores: {report['suppliers_created']}\n"
                f"- Productos creados: {report['products_created']} (actualizados: {report['products_updated']})\n"
                f"- Clientes creados: {report['clients_created']} (actualizados: {report['clients_updated']})\n"
                f"- Movimientos registrados: {report['movements_imported']}"
            )

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=bool(app.config.get('DEBUG', False)))
