import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

INSECURE_SECRET_KEYS = {
    '',
    'dev',
    'secret',
    'changeme',
    'citypet-super-secret-key-production-change-me-2026',
    'cambiar_por_una_clave_secreta_fuerte_y_aleatoria',
}


def normalize_database_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    url = raw_url.strip()
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+psycopg2://', 1)
    elif url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    return url


def build_engine_options(db_uri: str) -> dict:
    if db_uri and 'postgresql' in db_uri:
        return {
            'pool_pre_ping': True,
            'pool_recycle': int(os.environ.get('DB_POOL_RECYCLE', 300)),
            'pool_size': int(os.environ.get('DB_POOL_SIZE', 5)),
            'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW', 10)),
        }
    return {
        'pool_pre_ping': True,
    }


class Config:
    APP_ENV = os.environ.get('APP_ENV') or os.environ.get('FLASK_CONFIG') or 'development'
    SECRET_KEY = os.environ.get('SECRET_KEY', 'citypet-super-secret-key-production-change-me-2026')
    CITYPET_ENCRYPTION_KEY = os.environ.get('CITYPET_ENCRYPTION_KEY', '')

    # Handle database URL (supports postgres:// conversion for Render / Supabase)
    _db_url = normalize_database_url(os.environ.get('DATABASE_URL'))
    if _db_url:
        SQLALCHEMY_DATABASE_URI = _db_url
    else:
        default_db_path = os.path.join(BASE_DIR, 'citypet.db')
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{default_db_path}'

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = build_engine_options(SQLALCHEMY_DATABASE_URI)

    # Session & Security
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 7200

    # Uploads & Storage
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max request payload
    MAX_IMAGE_SIZE_BYTES = int(os.environ.get('MAX_IMAGE_SIZE_BYTES', 5 * 1024 * 1024))  # 5MB max per image
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'xlsx', 'xls'}
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    ALLOWED_EXCEL_EXTENSIONS = {'xlsx', 'xls'}

    # Business Information (Default fallback, configurable in DB SystemSetting)
    COMPANY_NAME = "CITYPET PHARMA"
    COMPANY_SLOGAN = "Salud especializada para tu mejor amigo."
    COMPANY_RUC = "0010712900023W"
    COMPANY_ADDRESS = "Col. Cristian Pérez, ddf el Cine Rex 50 vrs. al Norte"
    COMPANY_PHONE = "(+505) 8363-7606"
    COMPANY_CURRENCY = "C$"
    COMPANY_COUNTRY = "Nicaragua"

    # Telegram defaults (overridden by SystemSetting unless force-disabled by environment)
    TELEGRAM_ENABLED = os.environ.get('TELEGRAM_ENABLED', 'false').strip().lower() == 'true'
    TELEGRAM_FORCE_DISABLED = os.environ.get('TELEGRAM_FORCE_DISABLED', 'false').strip().lower() == 'true'
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

    # Supabase Storage Configuration (independent per environment)
    SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    SUPABASE_STORAGE_BUCKET = os.environ.get('SUPABASE_STORAGE_BUCKET', 'product-images')

    # Environment Isolation Controls
    STRICT_ENV_VALIDATION = False


class DevelopmentConfig(Config):
    APP_ENV = 'development'
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    STRICT_ENV_VALIDATION = False


class StagingConfig(Config):
    """
    Entorno STAGING (Pruebas del sistema y evaluación del cliente).
    - Base de datos independiente en Supabase Testing.
    - Almacenamiento independiente.
    - Telegram desactivado por defecto.
    - Sin acceso a datos ni recursos de producción.
    """
    APP_ENV = 'staging'
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_NAME = 'citypet_staging_session'
    STRICT_ENV_VALIDATION = True
    TELEGRAM_ENABLED = os.environ.get('TELEGRAM_ENABLED', 'false').strip().lower() == 'true'
    SUPABASE_STORAGE_BUCKET = os.environ.get('SUPABASE_STORAGE_BUCKET', 'citypet-staging-media')


class ProductionConfig(Config):
    """
    Entorno PRODUCTION (Operación comercial oficial del negocio).
    - Base de datos comercial real en Supabase Production.
    - Almacenamiento comercial independiente.
    - Seguridad reforzada, cookies HTTPS, sin herramientas ni rutas de prueba.
    """
    APP_ENV = 'production'
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_NAME = 'citypet_prod_session'
    STRICT_ENV_VALIDATION = True
    TELEGRAM_ENABLED = os.environ.get('TELEGRAM_ENABLED', 'true').strip().lower() == 'true'
    SUPABASE_STORAGE_BUCKET = os.environ.get('SUPABASE_STORAGE_BUCKET', 'citypet-production-media')


class TestConfig(Config):
    APP_ENV = 'testing'
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    TELEGRAM_ENABLED = False
    STRICT_ENV_VALIDATION = False


config = {
    'development': DevelopmentConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
    'testing': TestConfig,
    'default': DevelopmentConfig
}


CONFIG_ALIASES = {
    'default': 'development',
    'dev': 'development',
    'development': 'development',
    'staging': 'staging',
    'stage': 'staging',
    'prod': 'production',
    'production': 'production',
    'test': 'testing',
    'testing': 'testing',
}


def resolve_config_name(config_name: str | None = None) -> str:
    if config_name:
        raw_name = config_name.strip().lower()
    else:
        raw_name = (os.environ.get('APP_ENV') or os.environ.get('FLASK_CONFIG') or 'development').strip().lower()
    name = CONFIG_ALIASES.get(raw_name, raw_name)
    if name not in config:
        raise RuntimeError(
            f"Configuración de entorno desconocida: '{raw_name}'. "
            f"Valores válidos para APP_ENV / FLASK_CONFIG: development, staging, production, testing."
        )
    return name


def apply_runtime_environment_overrides(app, resolved_name: str):
    """
    Refreshes environment-driven configuration values at app creation time
    and enforces strict isolation between staging and production.
    """
    if resolved_name == 'testing':
        app.config['APP_ENV'] = 'testing'
        return

    env_secret = os.environ.get('SECRET_KEY')
    if env_secret is not None:
        app.config['SECRET_KEY'] = env_secret

    env_enc_key = os.environ.get('CITYPET_ENCRYPTION_KEY')
    if env_enc_key is not None:
        app.config['CITYPET_ENCRYPTION_KEY'] = env_enc_key

    env_db_url = normalize_database_url(os.environ.get('DATABASE_URL'))
    if env_db_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = env_db_url
    elif resolved_name in ('staging', 'production'):
        # Never fall back silently to local citypet.db in staging or production!
        app.config['SQLALCHEMY_DATABASE_URI'] = ''

    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = build_engine_options(app.config.get('SQLALCHEMY_DATABASE_URI', ''))

    # Refresh Telegram & Supabase Storage variables dynamically
    if 'TELEGRAM_BOT_TOKEN' in os.environ:
        app.config['TELEGRAM_BOT_TOKEN'] = os.environ['TELEGRAM_BOT_TOKEN']
    if 'TELEGRAM_CHAT_ID' in os.environ:
        app.config['TELEGRAM_CHAT_ID'] = os.environ['TELEGRAM_CHAT_ID']
    if 'PRODUCTION_TELEGRAM_CHAT_ID' in os.environ:
        app.config['PRODUCTION_TELEGRAM_CHAT_ID'] = os.environ['PRODUCTION_TELEGRAM_CHAT_ID']
    if 'TELEGRAM_ENABLED' in os.environ:
        app.config['TELEGRAM_ENABLED'] = os.environ['TELEGRAM_ENABLED'].strip().lower() == 'true'
    if 'TELEGRAM_FORCE_DISABLED' in os.environ:
        app.config['TELEGRAM_FORCE_DISABLED'] = os.environ['TELEGRAM_FORCE_DISABLED'].strip().lower() == 'true'

    if 'SUPABASE_URL' in os.environ:
        app.config['SUPABASE_URL'] = os.environ['SUPABASE_URL'].strip()
    if 'SUPABASE_KEY' in os.environ or 'SUPABASE_SERVICE_ROLE_KEY' in os.environ:
        app.config['SUPABASE_KEY'] = (os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
    if 'SUPABASE_STORAGE_BUCKET' in os.environ:
        app.config['SUPABASE_STORAGE_BUCKET'] = os.environ['SUPABASE_STORAGE_BUCKET'].strip()

    if app.config.get('STRICT_ENV_VALIDATION'):
        validate_environment_isolation(app)


def validate_environment_isolation(app):
    """
    Fail-safe validation for deployed environments (staging & production).
    Prevents missing secrets, insecure defaults, silent SQLite fallbacks,
    and any accidental cross-connection between staging and production.
    """
    app_env = app.config.get('APP_ENV', '').lower()
    if app_env not in ('staging', 'production'):
        return

    # 1. DEBUG must always be False in staging and production
    if app.config.get('DEBUG'):
        raise RuntimeError(f"Seguridad: DEBUG no puede estar activo en el entorno '{app_env}'.")

    # 2. Validate SECRET_KEY
    secret_key = (app.config.get('SECRET_KEY') or '').strip()
    if secret_key in INSECURE_SECRET_KEYS or len(secret_key) < 16:
        raise RuntimeError(
            f"Seguridad [{app_env}]: SECRET_KEY es obligatoria, debe ser única por entorno y tener al menos 16 caracteres."
        )

    # Check if staging and production share the same key if comparison env var is present
    other_secret = os.environ.get('PRODUCTION_SECRET_KEY' if app_env == 'staging' else 'STAGING_SECRET_KEY', '').strip()
    if other_secret and secret_key == other_secret:
        raise RuntimeError(
            f"Violación de aislamiento [{app_env}]: SECRET_KEY no puede ser idéntica entre staging y production."
        )

    # 3. Validate DATABASE_URL presence and prevent accidental fallback to local citypet.db
    db_uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip()
    if not db_uri:
        raise RuntimeError(
            f"Configuración crítica faltante [{app_env}]: La variable obligatoria DATABASE_URL no está configurada. "
            f"El sistema se detuvo por seguridad para evitar usar una base de datos incorrecta."
        )

    default_local_sqlite = os.path.join(BASE_DIR, 'citypet.db').replace('\\', '/').lower()
    allow_local_sqlite = os.environ.get('ALLOW_SQLITE_IN_DEPLOY', 'false').strip().lower() == 'true'
    if db_uri.startswith('sqlite:///') and not allow_local_sqlite:
        raise RuntimeError(
            f"Seguridad [{app_env}]: En '{app_env}' se requiere una conexión PostgreSQL dedicada (DATABASE_URL). "
            f"No se permite usar SQLite local por defecto."
        )
    norm_uri = db_uri.replace('\\', '/').lower()
    if allow_local_sqlite and (default_local_sqlite in norm_uri or norm_uri.endswith('/citypet.db')):
        raise RuntimeError(
            f"Violación de aislamiento [{app_env}]: Incluso en modo de prueba local, '{app_env}' no puede conectarse "
            f"al archivo principal de desarrollo 'citypet.db'. Use una base de datos aislada independiente."
        )

    # 4. Cross-Environment Isolation Guards (Staging vs Production)
    db_uri_lower = db_uri.lower()
    db_target_lower = os.path.basename(db_uri_lower) if db_uri_lower.startswith('sqlite:') else db_uri_lower
    supa_url_lower = (app.config.get('SUPABASE_URL') or '').strip().lower()
    bucket_lower = (app.config.get('SUPABASE_STORAGE_BUCKET') or '').strip().lower()

    if app_env == 'staging':
        # Staging MUST NEVER connect to any resource labeled production
        forbidden_markers = ('citypet-production', 'citypet_production', 'citypet-prod', 'citypet_prod', '-production', '_production')
        for marker in forbidden_markers:
            if marker in db_target_lower:
                raise RuntimeError(
                    f"VIOLACIÓN CRÍTICA DE AISLAMIENTO: El entorno 'staging' detectó un identificador de producción ('{marker}') en DATABASE_URL."
                )
            if marker in supa_url_lower:
                raise RuntimeError(
                    f"VIOLACIÓN CRÍTICA DE AISLAMIENTO: El entorno 'staging' detectó un proyecto Supabase de producción ('{marker}') en SUPABASE_URL."
                )
            if marker in bucket_lower:
                raise RuntimeError(
                    f"VIOLACIÓN CRÍTICA DE AISLAMIENTO: El entorno 'staging' no puede usar el bucket de producción ('{bucket_lower}')."
                )

        prod_db_ref = normalize_database_url(os.environ.get('PRODUCTION_DATABASE_URL'))
        if prod_db_ref and db_uri == prod_db_ref:
            raise RuntimeError(
                "VIOLACIÓN CRÍTICA DE AISLAMIENTO: DATABASE_URL de staging coincide con PRODUCTION_DATABASE_URL."
            )

        prod_chat_ref = (os.environ.get('PRODUCTION_TELEGRAM_CHAT_ID') or '').strip()
        curr_chat = (app.config.get('TELEGRAM_CHAT_ID') or '').strip()
        if prod_chat_ref and curr_chat and curr_chat == prod_chat_ref:
            raise RuntimeError(
                "VIOLACIÓN CRÍTICA DE AISLAMIENTO: TELEGRAM_CHAT_ID de staging no puede ser el chat comercial de producción."
            )

    elif app_env == 'production':
        # Production MUST NEVER connect to any resource labeled staging or testing
        forbidden_markers = ('citypet-staging', 'citypet_staging', 'citypet-testing', 'citypet_testing', '-staging', '_staging', '-testing', '_testing')
        for marker in forbidden_markers:
            if marker in db_target_lower:
                raise RuntimeError(
                    f"VIOLACIÓN CRÍTICA DE AISLAMIENTO: El entorno 'production' detectó un identificador de pruebas ('{marker}') en DATABASE_URL."
                )
            if marker in supa_url_lower:
                raise RuntimeError(
                    f"VIOLACIÓN CRÍTICA DE AISLAMIENTO: El entorno 'production' detectó un proyecto Supabase de pruebas ('{marker}') en SUPABASE_URL."
                )
            if marker in bucket_lower:
                raise RuntimeError(
                    f"VIOLACIÓN CRÍTICA DE AISLAMIENTO: El entorno 'production' no puede usar un bucket de pruebas ('{bucket_lower}')."
                )

        staging_db_ref = normalize_database_url(os.environ.get('STAGING_DATABASE_URL'))
        if staging_db_ref and db_uri == staging_db_ref:
            raise RuntimeError(
                "VIOLACIÓN CRÍTICA DE AISLAMIENTO: DATABASE_URL de production coincide con STAGING_DATABASE_URL."
            )
