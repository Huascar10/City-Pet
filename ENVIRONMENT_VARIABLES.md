# VARIABLES DE ENTORNO — CITYPET PHARMA

Este documento detalla todas las variables de entorno admitidas por **CityPet Pharma**, su obligatoriedad y los valores que deben configurarse en **Desarrollo Local**, **Staging (`citypet-testing`)** y **Producción (`citypet-production`)**.

---

## 1. Tabla Maestra de Variables de Entorno

| Variable | Obligatoria en Staging/Prod | Descripción | Valor en `development` (Local) | Valor en `staging` (`citypet-testing`) | Valor en `production` (`citypet-production`) |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `APP_ENV` | **SÍ** | Define el entorno lógico activo y activa las guardas de seguridad y aislamiento. | `development` | `staging` | `production` |
| `FLASK_CONFIG` | Recomendada | Alias de configuración de Flask (sincronizado con `APP_ENV`). | `development` | `staging` | `production` |
| `SECRET_KEY` | **SÍ** | Clave criptográfica para firmar cookies de sesión, tokens CSRF y cifrado Fernet (`ENCv1:`) de credenciales en BD. **Debe ser distinta en cada entorno** y tener al menos 16 caracteres (recomendado 64 hex). | Clave local de desarrollo | Clave aleatoria exclusiva de Staging | Clave aleatoria exclusiva de Producción |
| `DATABASE_URL` | **SÍ** | Cadena de conexión a la base de datos. En Staging y Producción no existe fallback a SQLite: si falta, la aplicación aborta el arranque de forma segura. | `sqlite:///citypet.db` (por defecto) | URI PostgreSQL de **Supabase Testing** (`?sslmode=require`) | URI PostgreSQL de **Supabase Production** (`?sslmode=require`) |
| `SUPABASE_URL` | Recomendada | URL base del proyecto de Supabase para almacenamiento persistente de imágenes. | Vacío (usa `static/uploads/`) | `https://<ref-staging>.supabase.co` | `https://<ref-prod>.supabase.co` |
| `SUPABASE_KEY` | Recomendada | Clave `service_role` del proyecto Supabase correspondiente (solo en servidor). | Vacío | Service Role Key de Supabase Testing | Service Role Key de Supabase Production |
| `SUPABASE_STORAGE_BUCKET` | Recomendada | Nombre del bucket de Supabase Storage donde se guardarán fotos de productos y logotipos. | `citypet-dev-media` | `citypet-staging-media` | `citypet-production-media` |
| `TELEGRAM_ENABLED` | No | Estado inicial por defecto de las notificaciones de Telegram si no se ha sobreescrito en la tabla `system_settings`. | `false` | `false` | `true` |
| `TELEGRAM_FORCE_DISABLED` | No | Si es `true`, bloquea por completo cualquier envío a Telegram incluso si está activado en la interfaz web. | `false` | `false` (o `true` si se desea bloqueo total) | `false` |
| `TELEGRAM_BOT_TOKEN` | No | Token inicial del bot de Telegram (también configurable y cifrado desde la interfaz web de Propietario). | Vacío | Vacío o token de bot de pruebas | Token del bot oficial de CityPet |
| `TELEGRAM_CHAT_ID` | No | Chat ID de destino para las alertas de Telegram. | Vacío | Vacío o Chat ID de grupo de pruebas | Chat ID oficial de gerencia |
| `PRODUCTION_TELEGRAM_CHAT_ID` | No | Opcional en `staging`: si se indica el Chat ID real de producción, `staging` bloqueará automáticamente cualquier intento de enviar mensajes a ese Chat ID. | Vacío | `<chat_id_real_de_produccion>` | Vacío |
| `ADMIN_INITIAL_PASSWORD` | Recomendada | Contraseña que asignará `flask init-db` al usuario `admin` cuando se inicializa una base de datos vacía. | `admin123` | Contraseña segura de pruebas | Contraseña fuerte del propietario |
| `MAX_IMAGE_SIZE_BYTES` | No | Tamaño máximo permitido por imagen subida en bytes (por defecto `5242880` = 5 MB). | `5242880` | `5242880` | `5242880` |
| `DB_POOL_SIZE` | No | Tamaño base del pool de conexiones SQLAlchemy para PostgreSQL. | `5` | `5` | `5` |
| `DB_MAX_OVERFLOW` | No | Conexiones adicionales máximas en picos de carga. | `10` | `10` | `10` |
| `DB_POOL_RECYCLE` | No | Segundos antes de reciclar conexiones en el pool (evita desconexiones por inactividad en Supabase Pooler). | `300` | `300` | `300` |
| `DB_CONNECT_TIMEOUT` | No | Tiempo máximo de espera (segundos) al establecer nueva conexión PostgreSQL. | `10` | `10` | `10` |
| `PYTHON_VERSION` | Recomendada en Render | Versión del runtime de Python en Render. | `3.11.9` | `3.11.9` | `3.11.9` |

---

## 2. Reglas Automáticas de Seguridad y Aislamiento (`config.py`)

El archivo `config.py` aplica validaciones estrictas durante el arranque de `create_app()`:

1. **Fallo seguro por falta de `SECRET_KEY`**:
   - En `staging` y `production`, si `SECRET_KEY` no está definida, tiene menos de 16 caracteres o coincide con el valor por defecto de desarrollo, el servidor **detiene su arranque inmediatamente** con un `RuntimeError` descriptivo.
2. **Fallo seguro por falta de `DATABASE_URL`**:
   - En `staging` y `production`, si `DATABASE_URL` no está definida, el servidor **no utiliza `citypet.db` como alternativa** sino que aborta el arranque para evitar pérdida de datos en discos efímeros.
3. **Normalización automática de URI PostgreSQL**:
   - Si `DATABASE_URL` comienza con `postgres://`, se convierte automáticamente a `postgresql://` para compatibilidad con SQLAlchemy 2.x.
4. **Bloqueo cruzado entre entornos (`validate_environment_isolation`)**:
   - Si `APP_ENV=staging`, el sistema **rechaza arrancar** si detecta que `DATABASE_URL`, `SUPABASE_URL` o `SUPABASE_STORAGE_BUCKET` contienen identificadores de producción (`citypet-production`, `prod-db`, `production-media`, etc.).
   - Si `APP_ENV=production`, el sistema **rechaza arrancar** si detecta que `DATABASE_URL`, `SUPABASE_URL` o `SUPABASE_STORAGE_BUCKET` contienen identificadores de pruebas (`staging`, `testing`).
5. **Seguridad de Cookies y HTTPS**:
   - En `staging` y `production`:
     - `DEBUG = False`
     - `SESSION_COOKIE_SECURE = True`
     - `REMEMBER_COOKIE_SECURE = True`
     - `SESSION_COOKIE_HTTPONLY = True`
     - `SESSION_COOKIE_SAMESITE = 'Lax'`
     - Nombres de cookie separados (`citypet_staging_session` vs `citypet_prod_session`) para evitar colisiones en el navegador.

---

## 3. Cómo Generar una `SECRET_KEY` Criptográficamente Segura

Ejecuta este comando dos veces en tu terminal (una para `staging` y otra distinta para `production`):

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

> **IMPORTANTE**: La `SECRET_KEY` también es utilizada por `CryptoService` para cifrar el token de Telegram (`ENCv1:...`) en la tabla `system_settings`. Una vez establecido un entorno en producción, conserva su `SECRET_KEY` en un lugar seguro. Si llegas a rotar la `SECRET_KEY`, solo deberás volver a guardar el token de Telegram en **Configuración -> Notificaciones Telegram**.
