# CityPet — Sistema Integral de Inventario y Gestión Comercial

Plataforma web profesional de gestión comercial, facturación, control de inventario y trazabilidad financiera, diseñada y personalizada específicamente para **CityPet Pharma** (Salud especializada para tu mejor amigo).

---

## 🐾 Características Principales

1. **Dashboard en Tiempo Real:**
   - Métricas calculadas directamente desde la base de datos (ventas del día, ingresos, gastos operativos, ganancia bruta estimada sobre costo real, valor del inventario al costo de adquisición).
   - Alertas visuales de stock bajo y productos agotados.
   - Gráfico interactivo de tendencia de ventas (Chart.js).
   - Listado de últimos movimientos de almacén y productos más vendidos.

2. **Catálogo de Productos y Existencias:**
   - Registro de productos con códigos únicos (`CP000001`), nombres, categorías veterinarias, almacén, código de barras, precio de venta y costo de compra.
   - Control de existencias calculado en tiempo real con regla estricta de **no permitir stock negativo**.
   - Conteo físico de bodega vs. existencia del sistema y cálculo de diferencias (faltantes/sobrantes) compatible con la estructura del Excel original.
   - Historial de trazabilidad individual por cada producto.

3. **Control de Inventario y Movimientos:**
   - Entradas: *Compras a proveedores, Regalías / Bonificaciones, Devoluciones de clientes, Ajustes de entrada, Inventario inicial*.
   - Salidas: *Ventas, Devoluciones a proveedores, Dañados / Mermas / Vencidos, Ajustes de salida*.
   - Transacciones atómicas de base de datos (`SELECT FOR UPDATE`).
   - Reversiones auditables (no se permite borrado silencioso de historial).

4. **Punto de Venta (POS) y Facturación:**
   - Buscador rápido predictivo de productos por nombre, código o lector de código de barras.
   - Carrito de compras interactivo con actualización en tiempo real de subtotales, descuentos y totales.
   - Selector de cliente (con preselección de cliente de mostrador genérico `CP-C0001 URBAN PETS`).
   - Métodos de pago configurables (Efectivo, Transferencia BAC/Banpro, Cheque, Tarjeta, Crédito).
   - Descuento en porcentaje y régimen fiscal (Cuota Fija / IVA 15%).
   - Generación automática de comprobante inmutable y salida de stock.

5. **Factura Idéntica a City Pet Pharma:**
   - Modelo de factura visual idéntica al documento oficial de la empresa (`City Pet Pharma _ Factura.pdf`), incorporando:
     - Logotipo oficial de CityPet Pharma con fondo transparente y alta resolución.
     - Datos fiscales (RUC: `0010712900023W`, Dirección en Colonia Cristian Pérez, Teléfono).
     - Tabla con cabeceras estilizadas (Código, Producto, Cantidad, Precio Unitario, DSCTO., Total).
     - Resumen con Cuota Fija, Subtotal y Total.
     - Firmas de *Entregué conforme* y *Recibí conforme*.
     - Cláusula legal de pagaré conforme al Arto. 38 de la Ley 732 del Banco Central de Nicaragua.
   - Vista apta para impresión directa (`window.print`) y descarga en PDF nativo (ReportLab).

6. **Compras a Proveedores (Fase 2):**
   - Módulo completo de compras (`/purchases`): selección de proveedor, factura externa física, múltiples productos con costo unitario, opción de actualizar el costo maestro del catálogo.
   - Incremento automático de existencias, registro de egreso financiero y emisión de comprobante de compra.
   - Anulación controlada con validación de stock disponible.

7. **Cuentas por Cobrar y Abonos (Fase 2):**
   - Control de facturas de crédito comercial con saldo pendiente (`/sales/abonos`).
   - Registro de abonos parciales o totales con validación `monto <= saldo`, actualización en tiempo real de `paid_amount` y emisión de recibo oficial de abono con saldo previo y saldo restante.

8. **Conciliación Matemática de Inventario (Fase 2):**
   - Herramienta de alta precisión (`/inventory/reconciliation`): valida matemáticamente `Stock Inicial + Entradas − Salidas = Stock Teórico` vs Stock Actual vs Conteo Físico.
   - Detección de descuadres y aplicación de ajustes compensatorios auditables en un solo clic.

9. **Previsualización de Recibos con Marca de Agua (Fase 2):**
   - Modales interactivos en POS, Compras y Abonos que generan la simulación del comprobante con la marca de agua `VISTA PREVIA — NO VÁLIDO COMO FACTURA` antes del guardado definitivo.

10. **Resúmenes Comerciales y Tendencias en UTC-6 (Fase 2):**
    - **Resumen Diario (`/reports/daily`):** Cierre del día ajustado a la zona horaria de Nicaragua (UTC-6 Managua) con flujo neto de caja, total facturado, abonos cobrados, compras, gastos y utilidad bruta.
    - **Resumen Mensual (`/reports/monthly`):** Rendimiento consolidado, margen bruto, ticket promedio, comparativa mes a mes (% MoM) y productos más y menos vendidos.
    - **Tendencias (`/reports/trends`):** Series de tiempo interactivas (7 días, 30 días, 3 meses, rango personalizado) con comparativa frente al período anterior.

11. **Apariencia, Paletas y Gestión de Logotipos (Fase 2):**
    - Configuración visual (`/settings/appearance`): modo Claro, Oscuro o Sistema.
    - Paletas veterinarias (Azul Médico `#1B4965`, Verde Selva `#2D6A4F`, Púrpura Real `#5A189A`, Naranja `#C25900`, o personalizada).
    - Carga de nuevos logotipos para la plataforma web y facturas, con botón de restablecimiento al logotipo oficial de la factura PDF.

12. **Roles y Permisos en Tres Niveles (Fase 2):**
    - `propietario`: Control total, gestión de usuarios, auditoría, configuración de Telegram y respaldos.
    - `administrador`: Control operativo: compras, ventas, inventario, clientes, finanzas y reportes.
    - `empleado`: Perfil de mostrador para POS, búsqueda de stock y emisión de ventas (costos y reportes confidenciales ocultos).

13. **Optimización Móvil y Tutorial Interactivo (Fase 2):**
    - Barra de navegación inferior móvil (`.citypet-bottom-nav`) fija en `<lg`, áreas táctiles $\ge 44\text{px}$.
    - Tutorial interactivo guiado de 25 pasos (`static/js/citypet-tour.js`) con spotlight, tarjetas flotantes y adaptación según el rol del usuario.

14. **Clientes y Proveedores:**
    - Directorio de más de 330 veterinarias y clientes con razón social, propietarios, teléfonos, vendedores asignados (`Lenin Montenegro`, `Asdrubal Zuniga`, `Mostrador`), días de crédito y límite de crédito.
    - Historial de compras y movimientos por cada cliente y proveedor.

15. **Movimientos Financieros (Flujo de Caja):**
    - Registro independiente de ingresos y gastos operativos (servicios básicos, alquileres, salarios, transporte, etc.) claramente diferenciado de las entradas/salidas de inventario.

8. **Importación y Exportación Excel:**
   - **Sincronización Maestra One-Click:** Importa y actualiza directamente desde `INVENTARIO NUEVO.xlsx` los catálogos de productos, clientes y movimientos históricos.
   - **Importador Flexible:** Carga cualquier archivo `.xlsx` o `.xls`, previsualiza hojas y filas, y permite mapear columnas personalizadas antes de confirmar la transacción.
   - **Exportación Profesional:** Generación de reportes tabulares en Excel (.xlsx) con estilos corporativos y en PDF.

9. **Integración con Telegram:**
   - Alertas instantáneas y no bloqueantes enviadas en segundo plano mediante hilos independientes.
   - Notificación de cada venta emitida (factura, cliente, total y productos).
   - Alertas de existencias bajas o stock agotado.
   - Panel de control para configurar Bot Token, Chat ID, conmutadores de eventos y botón de prueba de conexión.

10. **Seguridad y Auditoría:**
    - Autenticación con contraseñas cifradas (PBKDF2/Werkzeug).
    - Dos roles de usuario: **Propietario** (acceso total, auditoría, respaldos y usuarios) y **Administrador del Negocio** (operaciones comerciales).
    - Registro inmutable de auditoría (`AuditLog`) de todas las operaciones sensibles.
    - Exportación completa de respaldo en JSON.

---

## 🛠️ Arquitectura Tecnológica

- **Backend:** Python 3 + Flask 3 + SQLAlchemy 2 + Flask-Login + Flask-WTF (CSRF) + Flask-Migrate.
- **Frontend:** HTML5 semántico + CSS3 moderno (paleta CityPet) + JavaScript ES6 + Bootstrap 5.3 + Bootstrap Icons + Chart.js.
- **Reportes y Facturación:** ReportLab (generación PDF nativa) + OpenPyXL (manipulación Excel).
- **Base de Datos:** PostgreSQL en producción (compatible con Supabase) / SQLite localmente para desarrollo ágil.
- **Servidor de Producción:** Gunicorn.
- **Despliegue:** Preparado para Render con `Procfile` y `runtime.txt`.

---

## 🚀 Inicio Rápido en Desarrollo Local

### 1. Clonar o acceder al proyecto
```bash
cd c:\Users\huasc\Documents\CITYPET
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Inicializar la Base de Datos y el usuario administrador
```bash
flask init-db
```
> **Credenciales por defecto:**
> - Usuario: `admin`
> - Contraseña: `admin123`

### 4. Sincronizar el catálogo real desde `INVENTARIO NUEVO.xlsx`
```bash
flask seed-excel
```
Este comando cargará los 39 productos veterinarios, más de 330 clientes y los 2,690 movimientos históricos directamente a la base de datos local.

### 5. Iniciar el servidor web
```bash
python app.py
```
Abra su navegador en: **`http://localhost:5000`**

---

## 🧪 Pruebas Automatizadas

El proyecto cuenta con una batería de pruebas unitarias y de integración que verifican la autenticación, prevención de stock negativo, ventas, comprobantes inmutables, anulación de facturas y generación de PDFs:

```bash
python -m pytest tests/test_citypet.py -v
```

---

## 📁 Estructura del Código

```
CITYPET/
├── app.py                     # Inicialización del sistema, factoría y comandos CLI
├── config.py                  # Configuraciones por entorno (desarrollo, producción)
├── extensions.py              # Instancias de SQLAlchemy, LoginManager, CSRF
├── Procfile                   # Comando de arranque para Render (Gunicorn)
├── runtime.txt                # Versión de runtime Python
├── requirements.txt           # Dependencias fijadas del proyecto
├── .env.example               # Plantilla de variables de entorno
├── DEPLOY.md                  # Manual paso a paso para despliegue en Render y Supabase
│
├── models/                    # Modelos de datos
│   └── __init__.py            # User, Product, Client, Supplier, Sale, InventoryMovement, Receipt, etc.
│
├── routes/                    # Endpoints modulares (Blueprints)
│   ├── auth.py                # Login, logout, perfil y roles
│   ├── dashboard.py           # KPIs y estadísticas del negocio
│   ├── products.py            # Catálogo de productos, filtros y edición
│   ├── inventory.py           # Entradas, salidas, mermas y conteo físico
│   ├── sales.py               # Punto de venta (POS) y emisión de facturas
│   ├── clients.py             # Clientes, límites de crédito y vendedores
│   ├── suppliers.py           # Proveedores y compras
│   ├── finances.py            # Flujo de caja, ingresos y gastos operativos
│   ├── receipts.py            # Comprobantes, visor inmutable e impresión
│   ├── imports.py             # Asistente de importación de Excel con mapeo
│   ├── reports.py             # Informes analíticos y exportaciones Excel/PDF
│   └── settings.py            # Telegram, gestión de usuarios, respaldos y auditoría
│
├── services/                  # Lógica de negocio desacoplada
│   ├── inventory_service.py   # Control transaccional de stock y reversiones
│   ├── sales_service.py       # Procesamiento atómico de ventas
│   ├── receipt_service.py     # Generación de factura PDF con diseño oficial
│   ├── excel_service.py       # Lectura/escritura y parseo de Excel
│   ├── telegram_service.py    # Notificaciones en segundo plano
│   └── report_service.py      # Agregaciones estadísticas y financieras
│
├── static/                    # Archivos estáticos
│   ├── css/citypet.css        # Identidad visual corporativa y estilos de impresión
│   ├── js/citypet.js          # Lógica interactiva del cliente
│   ├── img/                   # Logotipo oficial y recursos gráficos
│   └── uploads/               # Imágenes de productos subidas
│
├── templates/                 # Plantillas HTML con Bootstrap 5
│   ├── base.html              # Layout principal responsive con sidebar
│   ├── auth/                  # Login y perfil
│   ├── dashboard/             # Dashboard de métricas y gráficos
│   ├── products/              # Catálogo y detalle de movimientos
│   ├── inventory/             # Movimientos de almacén y auditoría física
│   ├── sales/                 # Punto de venta y tabla de facturas
│   ├── clients/               # Gestión de clientes
│   ├── suppliers/             # Gestión de proveedores
│   ├── finances/              # Registro de gastos e ingresos
│   ├── receipts/              # Visor de comprobante y Factura Impresa idéntica
│   ├── imports/               # Asistente de importación y vista previa
│   ├── reports/               # Reportes ejecutivos
│   └── settings/              # Configuración de Telegram, usuarios y respaldos
│
└── tests/                     # Suite de pruebas automatizadas
    └── test_citypet.py        # Pruebas de integración
```
