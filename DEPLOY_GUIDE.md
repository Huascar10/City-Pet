# GUÍA DE DESPLIEGUE PROFESIONAL — CITYPET PHARMA

Esta guía documenta paso a paso cómo desplegar **CityPet Pharma** utilizando un único repositorio privado de **GitHub**, dos bases de datos y buckets independientes en **Supabase**, y dos servicios web aislados en **Render** (`staging` y `production`).

---

## 1. Arquitectura de Despliegue (Dos Entornos Independientes)

| Componente | Entorno de Pruebas (`STAGING`) | Entorno Oficial (`PRODUCTION`) |
| :--- | :--- | :--- |
| **Propósito** | Pruebas, demostraciones al cliente, validación de cambios | Operación comercial real de CityPet Pharma |
| **Rama de GitHub** | `staging` | `main` |
| **Servicio en Render** | `citypet-testing` (Plan Free) | `citypet-production` (Plan Starter o superior) |
| **Variable `APP_ENV`** | `staging` | `production` |
| **Proyecto Supabase** | `CityPet Testing` (Base de datos independiente) | `CityPet Production` (Base de datos real independiente) |
| **Bucket Supabase Storage** | `citypet-staging-media` (Público lectura / escritura vía API) | `citypet-production-media` (Público lectura / escritura vía API) |
| **Telegram** | Desactivado por defecto (`TELEGRAM_ENABLED=false`) o bot de pruebas (prefija `🧪 [STAGING]`) | Activado (`TELEGRAM_ENABLED=true`) con el Bot comercial real |
| **Cookie de Sesión** | `citypet_staging_session` (HTTPS Secure) | `citypet_prod_session` (HTTPS Secure) |

---

## 2. Paso 1: Crear los Dos Proyectos en Supabase (PostgreSQL + Storage)

1. Ingresa a [https://supabase.com/dashboard](https://supabase.com/dashboard).
2. **Crear el proyecto de pruebas (`CityPet Testing`)**:
   - Haz clic en **New Project**.
   - Nombre: `CityPet Testing`.
   - Define una contraseña segura para la base de datos y guárdala en un gestor de contraseñas.
   - Región recomendada: `US East (N. Virginia)` (o la más cercana a tu región en Render).
3. **Obtener la cadena `DATABASE_URL` de `CityPet Testing`**:
   - En el proyecto `CityPet Testing`, haz clic en el botón **Connect** (arriba) -> pestaña **Connection String** -> **URI**.
   - Selecciona el modo **Transaction Pooler (puerto 6543)** o **Session Pooler (puerto 5432)** compatible con IPv4 (Render utiliza IPv4 por defecto en sus contenedores).
   - Copia la URI y reemplaza `[YOUR-PASSWORD]` por la contraseña real. Añade `?sslmode=require` al final si no lo incluye:
     ```text
     postgresql://postgres.<project-ref-staging>:<password>@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
     ```
4. **Configurar Supabase Storage en `CityPet Testing`**:
   - En el menú izquierdo de Supabase, entra en **Storage** -> **New bucket**.
   - Nombre del bucket: `citypet-staging-media`.
   - Activa la opción **Public bucket** (para que los navegadores de escritorio y móvil puedan visualizar las fotos de productos y logotipos directamente mediante su URL pública HTTPS, mientras que la subida de archivos está restringida únicamente al backend de Flask mediante `SUPABASE_KEY`).
   - Ve a **Project Settings -> API** y copia:
     - `Project URL` -> será tu `SUPABASE_URL`.
     - `service_role secret` -> será tu `SUPABASE_KEY` (solo en las variables de entorno privadas de Render, **jamás** en el navegador).
5. **Crear el proyecto oficial (`CityPet Production`)**:
   - Repite los pasos anteriores creando un segundo proyecto totalmente separado llamado `CityPet Production`.
   - Crea su propio bucket público llamado `citypet-production-media`.
   - Obtén su propia `DATABASE_URL`, `SUPABASE_URL` y `SUPABASE_KEY`.

---

## 3. Paso 2: Subir el Proyecto al Repositorio Privado de GitHub

El repositorio Git local ya ha sido inicializado con las ramas `main` y `staging` y con `.gitignore` blindado para excluir `citypet.db`, `backups/`, `.env` y `INVENTARIO NUEVO.xlsx`.

1. Entra a [https://github.com/new](https://github.com/new).
2. Nombre del repositorio: `citypet-pharma`.
3. Visibilidad: selecciona **Private** (Privado).
4. **No** marques "Add a README file" ni ".gitignore" (el proyecto ya los tiene).
5. Haz clic en **Create repository**.
6. En la terminal dentro de la carpeta `c:\Users\huasc\Documents\CITYPET`, enlaza el repositorio remoto y sube ambas ramas (`main` y `staging`):
   ```powershell
   git remote add origin https://github.com/<TU_USUARIO>/citypet-pharma.git
   git push -u origin main
   git push -u origin staging
   ```

---

## 4. Paso 3: Crear el Servicio `citypet-testing` (STAGING) en Render

1. Ingresa a [https://dashboard.render.com](https://dashboard.render.com).
2. Haz clic en **New +** -> **Web Service**.
3. Conecta tu cuenta de GitHub y selecciona el repositorio privado `citypet-pharma`.
4. Configura los parámetros del servicio:
   - **Name**: `citypet-testing`
   - **Branch**: `staging`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt && flask sync-schema`
   - **Start Command**: `gunicorn app:app --workers 2 --threads 2 --timeout 120`
   - **Instance Type**: `Free`
5. En la sección **Environment Variables**, agrega las variables de `staging` (ver detalle en `ENVIRONMENT_VARIABLES.md`):
   - `APP_ENV` = `staging`
   - `FLASK_CONFIG` = `staging`
   - `PYTHON_VERSION` = `3.11.9`
   - `SECRET_KEY` = *(cadena aleatoria única de 64 caracteres hexadecimales)*
   - `DATABASE_URL` = *(URI PostgreSQL del proyecto Supabase `CityPet Testing`)*
   - `SUPABASE_URL` = *(URL del proyecto Supabase `CityPet Testing`)*
   - `SUPABASE_KEY` = *(Service Role Key del proyecto Supabase `CityPet Testing`)*
   - `SUPABASE_STORAGE_BUCKET` = `citypet-staging-media`
   - `TELEGRAM_ENABLED` = `false`
   - `ADMIN_INITIAL_PASSWORD` = *(contraseña inicial segura para el usuario `admin` en staging)*
6. En **Advanced** -> **Health Check Path**, escribe: `/health`.
7. Haz clic en **Create Web Service**.
8. Una vez finalizado el primer despliegue, inicializa el usuario propietario ejecutando en la pestaña **Shell** de Render (o localmente apuntando a la BD de staging):
   ```bash
   flask init-db
   ```

---

## 5. Paso 4: Crear el Servicio `citypet-production` (PRODUCTION) en Render

1. En Render Dashboard, haz clic en **New +** -> **Web Service**.
2. Selecciona el mismo repositorio `citypet-pharma`, pero apunta a la rama `main`:
   - **Name**: `citypet-production`
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt && flask sync-schema`
   - **Start Command**: `gunicorn app:app --workers 2 --threads 2 --timeout 120`
   - **Instance Type**: `Starter` (recomendado en producción para evitar suspensión por inactividad) o `Free` inicial.
3. En **Environment Variables**, configura las credenciales exclusivas de producción:
   - `APP_ENV` = `production`
   - `FLASK_CONFIG` = `production`
   - `PYTHON_VERSION` = `3.11.9`
   - `SECRET_KEY` = *(clave aleatoria DIFERente a la de staging, 64 caracteres hex)*
   - `DATABASE_URL` = *(URI PostgreSQL del proyecto Supabase `CityPet Production`)*
   - `SUPABASE_URL` = *(URL del proyecto Supabase `CityPet Production`)*
   - `SUPABASE_KEY` = *(Service Role Key del proyecto Supabase `CityPet Production`)*
   - `SUPABASE_STORAGE_BUCKET` = `citypet-production-media`
   - `TELEGRAM_ENABLED` = `true`
   - `TELEGRAM_BOT_TOKEN` = *(Token del bot oficial de CityPet Pharma)*
   - `TELEGRAM_CHAT_ID` = *(Chat ID oficial de gerencia CityPet Pharma)*
   - `ADMIN_INITIAL_PASSWORD` = *(Contraseña fuerte inicial del propietario)*
4. En **Health Check Path**, coloca `/health`.
5. Haz clic en **Create Web Service**.

---

## 6. Ejecución y Reversión de Migraciones de Base de Datos

CityPet incluye un doble mecanismo de migraciones no destructivas:
1. **Sincronización automática segura (`flask sync-schema`)**:
   - Crea cualquier tabla nueva declarada en los modelos SQLAlchemy si no existe.
   - Añade columnas nuevas de forma idempotente (`ALTER TABLE ... ADD COLUMN`) tanto en PostgreSQL como en SQLite sin borrar ni alterar registros existentes.
   - Sincroniza automáticamente todas las secuencias `SERIAL` (`pg_get_serial_sequence`) en PostgreSQL.
2. **Versionado con Flask-Migrate / Alembic (`migrations/`)**:
   - Para marcar una base de datos existente con la revisión inicial sin recrear tablas:
     ```bash
     flask db stamp head
     ```
   - Para aplicar migraciones versionadas en una base de datos nueva o existente:
     ```bash
     flask db upgrade
     ```
   - Para generar una nueva migración tras añadir un campo a `models/__init__.py`:
     ```bash
     flask db migrate -m "descripcion_del_cambio"
     flask db upgrade
     ```
   - Para revertir la última migración de Alembic:
     ```bash
     flask db downgrade -1
     ```

---

## 7. Migración Opcional de Imágenes Locales a Supabase Storage

Si deseas subir las imágenes locales existentes en `static/uploads/` hacia el bucket configurado en Supabase Storage y actualizar automáticamente las URLs de los productos y logotipos en la base de datos:

```bash
flask migrate-media
```

Este comando valida cada imagen local, la sube al bucket del entorno activo (`citypet-staging-media` o `citypet-production-media`), actualiza `Product.image_url` y `SystemSetting`, y **conserva intactos los archivos locales originales**.
