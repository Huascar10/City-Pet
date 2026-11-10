# LISTA DE VERIFICACIÓN DE DESPLIEGUE (DEPLOY CHECKLIST) — CITYPET PHARMA

Utiliza esta lista de control antes, durante y después de publicar en **Staging** y **Production**.

---

## 1. Verificación Previa en Local y GitHub

- [ ] Todos los tests automatizados pasan localmente (`python -m pytest -v`).
- [ ] El archivo `.gitignore` excluye `.env`, `*.db`, `backups/`, `static/uploads/*` y `INVENTARIO NUEVO.xlsx`.
- [ ] `git status --ignored` confirma que `citypet.db` y `backups/` están ignorados y **no** forman parte de ningún commit.
- [ ] No existen tokens de Telegram, contraseñas ni cadenas de conexión reales escritas en el código fuente.
- [ ] El repositorio en GitHub fue creado como **Private** (Privado).
- [ ] Existen las ramas `main` y `staging` en el repositorio.

---

## 2. Verificación del Entorno STAGING (`citypet-testing`)

- [ ] Proyecto de Supabase **CityPet Testing** creado con su propia contraseña.
- [ ] Bucket público `citypet-staging-media` creado en Supabase Storage (proyecto Testing).
- [ ] Servicio web `citypet-testing` creado en Render conectado a la rama `staging`.
- [ ] Variables de entorno en Render (`citypet-testing`) configuradas:
  - [ ] `APP_ENV=staging`
  - [ ] `FLASK_CONFIG=staging`
  - [ ] `SECRET_KEY` única (64 caracteres hex)
  - [ ] `DATABASE_URL` apuntando a Supabase Testing (`?sslmode=require`)
  - [ ] `SUPABASE_URL`, `SUPABASE_KEY` y `SUPABASE_STORAGE_BUCKET=citypet-staging-media`
  - [ ] `TELEGRAM_ENABLED=false`
- [ ] El endpoint `https://<tu-servicio-staging>.onrender.com/health` responde HTTP `200` con:
  ```json
  {
    "database": "connected",
    "environment": "staging",
    "status": "ok",
    "storage_backend": "supabase"
  }
  ```
- [ ] La barra superior del sistema muestra la insignia amarilla `ENTORNO DE PRUEBAS (STAGING)`.
- [ ] Se probó iniciar sesión, crear un producto con foto, registrar una venta de prueba y verificar que la imagen persiste en Supabase Storage (`citypet-staging-media`).
- [ ] Ninguna notificación de prueba llegó al chat comercial real de Telegram.

---

## 3. Verificación del Entorno PRODUCTION (`citypet-production`)

- [ ] Proyecto de Supabase **CityPet Production** creado (completamente independiente de Testing).
- [ ] Bucket público `citypet-production-media` creado en Supabase Storage (proyecto Production).
- [ ] Servicio web `citypet-production` creado en Render conectado a la rama `main`.
- [ ] Variables de entorno en Render (`citypet-production`) configuradas:
  - [ ] `APP_ENV=production`
  - [ ] `FLASK_CONFIG=production`
  - [ ] `SECRET_KEY` única (distinta de staging y de local)
  - [ ] `DATABASE_URL` apuntando a Supabase Production (`?sslmode=require`)
  - [ ] `SUPABASE_URL`, `SUPABASE_KEY` y `SUPABASE_STORAGE_BUCKET=citypet-production-media`
  - [ ] `TELEGRAM_ENABLED=true`
  - [ ] `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` reales
  - [ ] `ADMIN_INITIAL_PASSWORD` segura configurada
- [ ] El endpoint `https://<tu-servicio-production>.onrender.com/health` responde HTTP `200` con `"environment": "production"` y `"database": "connected"`.
- [ ] Se cambió la contraseña del usuario `admin` desde la interfaz o se verificó `ADMIN_INITIAL_PASSWORD`.
- [ ] Se cargó la información comercial real en Producción (mediante importación del respaldo JSON verificado desde **Configuración -> Respaldos y Restauración**).
- [ ] Se ejecutó `flask migrate-media` si había fotos locales previas que debían subirse a Supabase Storage.
- [ ] Se probó el botón **Enviar Mensaje de Prueba** en **Configuración -> Notificaciones Telegram** y se confirmó la recepción en el chat oficial sin exponer el token en pantalla.
- [ ] Se descargó un primer respaldo JSON (`CityPet_FullBackup_production_*.json`) tras la puesta en marcha inicial y se guardó en almacenamiento seguro externo.
