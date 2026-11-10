import os
import secrets
import logging
from io import BytesIO
from datetime import datetime
import requests
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename
from flask import current_app

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
ALLOWED_PILLOW_FORMATS = {'PNG', 'JPEG', 'WEBP'}
MIME_TYPES = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'webp': 'image/webp',
}
FORBIDDEN_SUBSTRINGS = ('.php', '.exe', '.sh', '.bat', '.cmd', '.js', '.html', '.htm', '.svg', '.py', '..')


class StorageValidationError(ValueError):
    """Raised when an uploaded file fails security, extension, size, or content validation."""
    pass


class StorageService:
    """
    Persistent and secure file storage manager for CityPet.
    Supports Supabase Storage (with environment-isolated buckets) and local filesystem storage.
    Never exposes private keys to the frontend and strictly validates file extension, size, and binary content.
    """

    @staticmethod
    def is_supabase_configured() -> bool:
        url = (current_app.config.get('SUPABASE_URL') or '').strip()
        key = (current_app.config.get('SUPABASE_KEY') or '').strip()
        bucket = (current_app.config.get('SUPABASE_STORAGE_BUCKET') or '').strip()
        return bool(url and key and bucket and url.startswith('https://'))

    @staticmethod
    def _check_bucket_isolation():
        """Ensures staging never writes to a production bucket and vice versa."""
        app_env = (current_app.config.get('APP_ENV') or 'development').lower()
        bucket = (current_app.config.get('SUPABASE_STORAGE_BUCKET') or '').lower()
        supa_url = (current_app.config.get('SUPABASE_URL') or '').lower()

        if app_env == 'staging' and ('production' in bucket or 'prod' in bucket or 'production' in supa_url):
            raise RuntimeError("Aislamiento de almacenamiento: Staging tiene prohibido escribir en un bucket de producción.")
        if app_env == 'production' and ('staging' in bucket or 'testing' in bucket or 'staging' in supa_url):
            raise RuntimeError("Aislamiento de almacenamiento: Production tiene prohibido escribir en un bucket de pruebas.")

    @classmethod
    def validate_image_file(cls, file_storage) -> tuple[bytes, str, str]:
        """
        Validates an uploaded image FileStorage object:
        1. Safe filename & extension check.
        2. Byte size limit check.
        3. Real image binary header & structure check via Pillow.
        Returns (raw_bytes, normalized_ext, mime_type).
        """
        if not file_storage or not getattr(file_storage, 'filename', None):
            raise StorageValidationError("No se seleccionó ningún archivo de imagen.")

        raw_filename = file_storage.filename.strip()
        lower_name = raw_filename.lower()

        for bad in FORBIDDEN_SUBSTRINGS:
            if bad in lower_name:
                raise StorageValidationError("Nombre de archivo rechazado por políticas de seguridad.")

        if '.' not in raw_filename:
            raise StorageValidationError("El archivo no tiene una extensión válida.")

        ext = raw_filename.rsplit('.', 1)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            raise StorageValidationError(
                f"Formato de imagen no permitido (.{ext}). Use únicamente: PNG, JPG, JPEG o WEBP."
            )

        raw_bytes = file_storage.read()
        file_storage.seek(0)

        if not raw_bytes or len(raw_bytes) == 0:
            raise StorageValidationError("El archivo de imagen está vacío.")

        max_bytes = int(current_app.config.get('MAX_IMAGE_SIZE_BYTES', 5 * 1024 * 1024))
        if len(raw_bytes) > max_bytes:
            max_mb = max_bytes / (1024 * 1024)
            raise StorageValidationError(f"La imagen supera el tamaño máximo permitido ({max_mb:.1f} MB).")

        # Verify actual image binary structure using Pillow
        try:
            with Image.open(BytesIO(raw_bytes)) as img:
                img.verify()
            with Image.open(BytesIO(raw_bytes)) as img2:
                real_format = (img2.format or '').upper()
                width, height = img2.size
        except (UnidentifiedImageError, Exception) as exc:
            raise StorageValidationError("El contenido del archivo no corresponde a una imagen válida o está dañado.") from exc

        if real_format not in ALLOWED_PILLOW_FORMATS:
            raise StorageValidationError(f"El contenido real del archivo ({real_format}) no es un formato de imagen permitido.")

        if width <= 0 or height <= 0 or width > 8192 or height > 8192:
            raise StorageValidationError("Las dimensiones de la imagen están fuera del rango permitido (máx. 8192x8192 px).")

        mime_type = MIME_TYPES.get(ext, 'image/png')
        return raw_bytes, ext, mime_type

    @classmethod
    def upload_bytes_to_supabase(cls, raw_bytes: bytes, remote_path: str, mime_type: str) -> str:
        """
        Uploads raw bytes to Supabase Storage REST API and returns the public URL.
        Never exposes SUPABASE_KEY in the returned URL or logs.
        """
        cls._check_bucket_isolation()
        supa_url = current_app.config['SUPABASE_URL'].rstrip('/')
        supa_key = current_app.config['SUPABASE_KEY'].strip()
        bucket = current_app.config['SUPABASE_STORAGE_BUCKET'].strip()

        clean_remote = remote_path.lstrip('/')
        upload_endpoint = f"{supa_url}/storage/v1/object/{bucket}/{clean_remote}"

        headers = {
            'Authorization': f"Bearer {supa_key}",
            'apikey': supa_key,
            'Content-Type': mime_type,
            'x-upsert': 'true',
        }

        resp = requests.post(upload_endpoint, data=raw_bytes, headers=headers, timeout=15)
        if resp.status_code not in (200, 201):
            logger.error("Error al subir archivo a Supabase Storage (HTTP %s).", resp.status_code)
            raise RuntimeError(f"No se pudo almacenar la imagen en Supabase Storage (HTTP {resp.status_code}).")

        public_url = f"{supa_url}/storage/v1/object/public/{bucket}/{clean_remote}"
        return public_url

    @classmethod
    def save_product_image(cls, file_storage, product_code: str = 'PROD') -> str:
        """
        Validates and saves a product image.
        Uses Supabase Storage when configured, while also keeping a local copy in static/uploads.
        Returns the URL to store in Product.image_url.
        """
        raw_bytes, ext, mime_type = cls.validate_image_file(file_storage)

        safe_code = secure_filename(str(product_code or 'PROD')) or 'PROD'
        ts = int(datetime.utcnow().timestamp())
        rand_suffix = secrets.token_hex(3)
        filename = f"prod_{safe_code}_{ts}_{rand_suffix}.{ext}"

        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        local_path = os.path.join(upload_folder, filename)
        with open(local_path, 'wb') as f:
            f.write(raw_bytes)

        if cls.is_supabase_configured():
            remote_path = f"products/{filename}"
            return cls.upload_bytes_to_supabase(raw_bytes, remote_path, mime_type)

        return f"/static/uploads/{filename}"

    @classmethod
    def save_logo_image(cls, file_storage, logo_type: str = 'system') -> str:
        """
        Validates and saves a custom system or receipt logo.
        """
        raw_bytes, ext, mime_type = cls.validate_image_file(file_storage)

        safe_type = 'receipt' if logo_type == 'receipt' else 'system'
        ts = int(datetime.utcnow().timestamp())
        rand_suffix = secrets.token_hex(3)
        filename = f"custom_{safe_type}_logo_{ts}_{rand_suffix}.{ext}"

        logos_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logos')
        os.makedirs(logos_folder, exist_ok=True)
        local_path = os.path.join(logos_folder, filename)
        with open(local_path, 'wb') as f:
            f.write(raw_bytes)

        if cls.is_supabase_configured():
            remote_path = f"logos/{filename}"
            return cls.upload_bytes_to_supabase(raw_bytes, remote_path, mime_type)

        return f"/static/uploads/logos/{filename}"

    @classmethod
    def validate_and_save_temp_excel(cls, file_storage, user_id: int) -> tuple[str, str]:
        """
        Validates an uploaded Excel file (.xlsx / .xls) and saves it to a secure temporary path.
        Returns (temp_filename, temp_full_path).
        """
        if not file_storage or not getattr(file_storage, 'filename', None):
            raise StorageValidationError("No se seleccionó ningún archivo Excel.")

        raw_name = file_storage.filename.strip()
        if not raw_name.lower().endswith(('.xlsx', '.xls')):
            raise StorageValidationError("El archivo debe tener formato Excel (.xlsx o .xls).")

        raw_bytes = file_storage.read()
        file_storage.seek(0)

        if not raw_bytes or len(raw_bytes) < 4:
            raise StorageValidationError("El archivo Excel está vacío o dañado.")

        max_bytes = int(current_app.config.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
        if len(raw_bytes) > max_bytes:
            raise StorageValidationError("El archivo Excel excede el tamaño máximo permitido (16 MB).")

        # Check ZIP/OOXML magic header (PK\x03\x04) for .xlsx or OLE2 (\xD0\xCF\x11\xE0) for .xls
        if raw_name.lower().endswith('.xlsx') and not raw_bytes.startswith(b'PK\x03\x04'):
            raise StorageValidationError("El archivo no tiene una estructura válida de libro Excel (.xlsx).")

        safe_base = secure_filename(raw_name) or 'import.xlsx'
        ts = int(datetime.utcnow().timestamp())
        token = secrets.token_hex(4)
        temp_filename = f"temp_import_{user_id}_{ts}_{token}_{safe_base}"

        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        temp_path = os.path.join(upload_folder, temp_filename)
        with open(temp_path, 'wb') as f:
            f.write(raw_bytes)

        return temp_filename, temp_path

    @classmethod
    def migrate_local_media_to_supabase(cls) -> dict:
        """
        Migrates existing local images in static/uploads/ to the configured Supabase Storage bucket
        and updates Product.image_url and SystemSetting logo URLs without deleting local files.
        """
        from extensions import db
        from models import Product, SystemSetting

        if not cls.is_supabase_configured():
            raise RuntimeError("Supabase Storage no está configurado (faltan SUPABASE_URL, SUPABASE_KEY o SUPABASE_STORAGE_BUCKET).")

        migrated_products = 0
        migrated_logos = 0
        errors = []

        upload_folder = current_app.config['UPLOAD_FOLDER']

        # 1. Migrate product images pointing to /static/uploads/...
        products = Product.query.filter(Product.image_url.like('/static/uploads/%')).all()
        for prod in products:
            rel_name = prod.image_url.replace('/static/uploads/', '', 1).lstrip('/')
            local_file = os.path.join(upload_folder, rel_name)
            if not os.path.exists(local_file):
                continue
            ext = local_file.rsplit('.', 1)[-1].lower() if '.' in local_file else 'png'
            mime = MIME_TYPES.get(ext, 'image/png')
            try:
                with open(local_file, 'rb') as f:
                    raw_b = f.read()
                public_url = cls.upload_bytes_to_supabase(raw_b, f"products/{os.path.basename(local_file)}", mime)
                prod.image_url = public_url
                migrated_products += 1
            except Exception as e:
                errors.append(f"Producto {prod.code}: {str(e)}")

        # 2. Migrate custom logos if pointing to /static/uploads/logos/...
        for key in ('system_logo_url', 'receipt_logo_url'):
            val = SystemSetting.get_val(key, '')
            if val and val.startswith('/static/uploads/'):
                rel_name = val.replace('/static/uploads/', '', 1).lstrip('/')
                local_file = os.path.join(upload_folder, rel_name)
                if os.path.exists(local_file):
                    ext = local_file.rsplit('.', 1)[-1].lower() if '.' in local_file else 'png'
                    mime = MIME_TYPES.get(ext, 'image/png')
                    try:
                        with open(local_file, 'rb') as f:
                            raw_b = f.read()
                        public_url = cls.upload_bytes_to_supabase(raw_b, f"logos/{os.path.basename(local_file)}", mime)
                        SystemSetting.set_val(key, public_url)
                        migrated_logos += 1
                    except Exception as e:
                        errors.append(f"Logo {key}: {str(e)}")

        db.session.commit()
        return {
            'migrated_products': migrated_products,
            'migrated_logos': migrated_logos,
            'errors': errors
        }
