# Guía de Despliegue en Producción: Render + Supabase

Esta guía detalla los pasos exactos para poner **CityPet** en producción en internet utilizando **Render** para el alojamiento web y **Supabase** para la base de datos PostgreSQL persistente.

---

## 1. Configuración de la Base de Datos en Supabase

1. Inicie sesión en [Supabase](https://supabase.com) y cree un nuevo proyecto (por ejemplo `citypet-db`).
2. Defina una contraseña segura para la base de datos y seleccione la región más cercana (ejemplo: `us-east-1`).
3. Una vez creado el proyecto, diríjase a **Project Settings > Database**.
4. En la sección **Connection string**, seleccione el modo **URI** (o Session / Transaction pooler en el puerto 5432 o 6543):
   ```
   postgresql://postgres:[TU_PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres
   ```
   *Guarde esta cadena de conexión; será su variable de entorno `DATABASE_URL`.*

---

## 2. Preparación del Repositorio Git

Asegúrese de que su proyecto esté bajo control de versiones Git y alojado en GitHub o GitLab:

```bash
git init
git add .
git commit -m "CityPet production prototype ready"
git remote add origin https://github.com/tu-usuario/citypet.git
git push -u origin main
```

*(Nota: Asegúrese de que archivos sensibles o temporales no estén incluidos. El repositorio ya cuenta con `.gitignore` preconfigurado).*

---

## 3. Despliegue en Render

1. Inicie sesión en [Render](https://render.com).
2. Haga clic en **New + > Web Service**.
3. Conecte su cuenta de GitHub/GitLab y seleccione el repositorio de `citypet`.
4. Configure los parámetros del servicio:
   - **Name:** `citypet` (o el nombre que prefiera).
   - **Region:** Seleccione la misma región que su base de datos de Supabase.
   - **Branch:** `main`.
   - **Root Directory:** *(dejar en blanco)*.
   - **Runtime:** `Python 3`.
   - **Build Command:**
     ```bash
     pip install -r requirements.txt
     ```
   - **Start Command:**
     ```bash
     gunicorn app:app --log-file -
     ```
5. En la sección **Environment Variables**, agregue las siguientes variables:

| Variable | Valor |
| :--- | :--- |
| `FLASK_CONFIG` | `production` |
| `FLASK_APP` | `app.py` |
| `SECRET_KEY` | *(Genere una cadena larga aleatoria, por ej. `openssl rand -hex 32`)* |
| `DATABASE_URL` | *(Su URL de conexión de Supabase obtenida en el paso 1)* |
| `TELEGRAM_BOT_TOKEN` | *(Opcional, su bot token de Telegram)* |
| `TELEGRAM_CHAT_ID` | *(Opcional, su chat ID de Telegram)* |

6. Haga clic en **Create Web Service**.

---

## 4. Inicialización de Tablas y Carga de Datos en Producción

Una vez que Render complete el primer despliegue con éxito:

1. En el panel de Render de su Web Service, abra la pestaña **Shell**.
2. Ejecute el comando de inicialización de la base de datos:
   ```bash
   flask init-db
   ```
   Esto creará todas las tablas en Supabase y el usuario propietario inicial:
   - **Usuario:** `admin`
   - **Contraseña:** `admin123` *(Cámbiela inmediatamente desde la pantalla "Mi Perfil" tras el primer inicio de sesión)*.

3. *(Opcional)* Si desea sincronizar el catálogo inicial completo de productos y clientes desde el archivo `INVENTARIO NUEVO.xlsx`:
   ```bash
   flask seed-excel
   ```
   o bien ingrese al sistema desde el navegador y pulse **"Sincronizar Datos desde INVENTARIO NUEVO.xlsx"** en la sección *Importación Excel*.

---

## 5. Configuración de Almacenamiento Persistente para Imágenes (Opcional)

Si desea subir fotografías de productos que persistan permanentemente:
1. En Supabase, diríjase a **Storage** y cree un Bucket público llamado `product-images`.
2. En Render, agregue las variables de entorno:
   - `SUPABASE_URL`: `https://[PROJECT_REF].supabase.co`
   - `SUPABASE_KEY`: *(Su clave service_role o anon)*
   - `SUPABASE_STORAGE_BUCKET`: `product-images`

---

## 6. Verificación Final

Acceda a la URL generada por Render (ejemplo: `https://citypet.onrender.com`):
1. Inicie sesión con `admin` / `admin123`.
2. Verifique que el Dashboard cargue las métricas correctamente desde Supabase PostgreSQL.
3. Diríjase a **Punto de Venta (POS)**, realice una venta de prueba y verifique la generación de la **Factura Impresa con el diseño oficial de CityPet Pharma**.
4. Configure la integración de **Telegram** en el menú de configuración y ejecute la prueba de conexión.
