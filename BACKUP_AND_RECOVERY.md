# RESPALDOS, RECUPERACIÓN Y PROTECCIÓN DE DATOS — CITYPET PHARMA

Este documento detalla la estrategia de copias de seguridad, verificación criptográfica en base de datos aislada, sincronización de secuencias PostgreSQL y procedimientos de recuperación ante desastres para **CityPet Pharma**.

---

## 1. Capas de Protección de Datos en CityPet Pharma

CityPet cuenta con **tres niveles complementarios de protección** para garantizar cero pérdida de información comercial:

1. **Respaldos Relacionales Integrales con Firma SHA-256 desde la Interfaz Web (`BackupService`)**:
   - Exporta en un único archivo JSON (`CityPet_FullBackup_<environment>_<YYYYMMDD_HHMMSS>.json`) las **16 tablas operativas y de catálogo** en orden relacional estricto (`users`, `system_settings`, `suppliers`, `clients`, `products`, `sales`, `sale_items`, `credit_exceptions`, `purchases`, `purchase_items`, `receipts`, `payments`, `purchase_payments`, `inventory_movements`, `financial_movements`, `audit_logs`) más los archivos multimedia locales codificados en Base64 con su hash SHA-256 individual.
   - Incluye metadatos de integridad (`counts` exactos por tabla, `environment` de origen y `checksum_sha256` global).
2. **Verificación en Base de Datos Aislada antes de Restaurar**:
   - Antes de tocar un solo registro de la base de datos activa, `BackupService.verify_backup_in_isolated_db()` levanta una base de datos temporal en memoria (`sqlite:///:memory:`), restaura allí todo el archivo JSON, comprueba todas las claves foráneas y compara el conteo de cada tabla contra los metadatos del respaldo. Si cualquier tabla o checksum falla, la restauración se aborta sin modificar la base de datos real.
3. **Aislamiento Cruzado de Entornos y Sincronización Automática de Secuencias PostgreSQL**:
   - **Bloqueo de contaminación Staging → Production**: Si un archivo de respaldo tiene `metadata.environment` igual a `"staging"` o `"testing"`, el entorno `"production"` **bloquea automáticamente su restauración** para impedir que datos ficticios de prueba sobrescriban la información comercial real del negocio.
   - **Sincronización de secuencias `SERIAL` en PostgreSQL (`sync_postgres_sequences`)**: Al restaurar registros con `id` explícito en Supabase PostgreSQL, CityPet actualiza automáticamente todas las secuencias (`setval(pg_get_serial_sequence(...))`) para que las siguientes ventas, compras, productos o recibos continúen su numeración sin errores de clave duplicada (`UniqueViolation`).

---

## 2. Cómo Generar y Descargar un Respaldo Completo (Manual o Programado)

### Opción A: Desde la Interfaz Web (Recomendado para el Propietario)
1. Inicia sesión con una cuenta de rol **Propietario**.
2. En la barra superior derecha, haz clic en el botón de **Configuración (ícono de engranaje ⚙️)** -> **Respaldos y Restauración**.
3. En la tarjeta **1. Exportar Respaldo Completo**, haz clic en **Descargar Respaldo Completo (.JSON)**.
4. Guarda el archivo `CityPet_FullBackup_production_YYYYMMDD_HHMMSS.json` en una carpeta segura en tu computadora o nube privada (Google Drive / OneDrive del negocio).

> **Frecuencia recomendada en Producción**:
> - Al cierre de cada semana operativa.
> - Siempre **antes** de realizar una importación masiva de Excel o de promover cambios nuevos de `staging` a `main`.

### Opción B: Desde Terminal / Línea de Comandos Python
```powershell
python -c "from app import create_app; from services.backup_service import BackupService; app = create_app(); app.app_context().push(); BackupService.save_backup_file('backups/respaldo_manual.json', exported_by='cli')"
```

---

## 3. Cómo Verificar un Archivo de Respaldo sin Modificar Datos Reales

Si deseas comprobar que un archivo `.json` descargado es 100% íntegro y restaurable sin alterar la base de datos activa:

1. Ve a **Configuración (⚙️) -> Respaldos y Restauración**.
2. En la tarjeta **2. Verificar Integridad de Respaldo (Prueba Aislada)**, selecciona tu archivo `.json`.
3. Haz clic en **Verificar en Base Aislada**.
4. El sistema mostrará el conteo exacto verificado de productos, clientes, proveedores, ventas, compras y movimientos.

---

## 4. Cómo Restaurar un Respaldo Completo en Caso de Contingencia

1. Ve a **Configuración (⚙️) -> Respaldos y Restauración**.
2. En la tarjeta **3. Restaurar Sistema desde Respaldo**, selecciona el archivo `.json` correspondiente al entorno activo.
3. Escribe la frase de confirmación requerida (`RESTAURAR SISTEMA`) y tu contraseña actual de Propietario.
4. Al confirmar:
   - El sistema verifica primero el archivo en una base de datos aislada en memoria.
   - Genera automáticamente una copia de seguridad previa (`backups/auto_pre_restore_<env>_<timestamp>.json`).
   - Restaura todas las tablas en una única transacción atómica (si ocurre cualquier error de red o base de datos, ejecuta `ROLLBACK` dejando intacto el estado anterior).
   - Sincroniza todas las secuencias `SERIAL` de PostgreSQL (`BackupService.sync_postgres_sequences`).
   - Registra el evento en la **Bitácora de Auditoría** (`RESTORE_FULL_BACKUP`).

---

## 5. Cómo Cargar tus Datos Locales Actuales hacia Supabase (Staging o Production)

Para llevar los datos actuales de tu base local (`citypet.db`) hacia Supabase PostgreSQL sin perder absolutamente ningún registro:

1. **En tu entorno local (`development`)**:
   - Inicia la aplicación local o ejecuta:
     ```powershell
     python -c "from app import create_app; from services.backup_service import BackupService; app = create_app('development'); app.app_context().push(); BackupService.save_backup_file('backups/migracion_inicial_supabase.json', exported_by='migracion_inicial')"
     ```
2. **En el servicio desplegado en Render (`citypet-testing` o `citypet-production`)**:
   - Inicia sesión como Propietario (`admin`).
   - Entra a **Configuración (⚙️) -> Respaldos y Restauración**.
   - Sube el archivo `migracion_inicial_supabase.json` en la sección de restauración.
   - Si además deseas subir las fotos de productos locales al bucket de Supabase Storage, ejecuta:
     ```powershell
     flask migrate-media
     ```
