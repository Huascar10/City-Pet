# FLUJO DE TRABAJO STAGING → PRODUCTION — CITYPET PHARMA

Este documento describe el flujo de trabajo oficial con ramas de GitHub (`staging` y `main`) para desarrollar mejoras, probarlas junto al cliente en **Staging (`citypet-testing`)** y promoverlas con seguridad hacia **Producción (`citypet-production`)** sin poner en riesgo los datos comerciales reales.

---

## 1. Diagrama del Flujo de Trabajo

```text
[Desarrollo Local]
       │
       ▼  (git push origin staging)
[Rama GitHub: staging] ──(Auto-Deploy)──► [Render: citypet-testing] + [Supabase Testing]
       │                                  (Pruebas técnicas y revisión del cliente)
       │
       ▼  (Aprobado por el cliente -> git checkout main && git merge staging && git push origin main)
[Rama GitHub: main]    ──(Auto-Deploy)──► [Render: citypet-production] + [Supabase Production]
                                          (Operación comercial real en vivo)
```

---

## 2. Regla de Oro

- **Todo cambio de código, diseño o funcionalidad nueva se realiza y prueba primero en la rama `staging`.**
- **Nunca se programa ni se empuja código sin probar directamente a la rama `main`.**
- **El código viaja de `staging` a `main`, pero los datos de la base de datos NUNCA viajan de `staging` a `production`.**

---

## 3. Paso a Paso para Desarrollar y Publicar un Cambio en STAGING

### Paso 1: Ubicarse en la rama `staging` localmente
```powershell
git checkout staging
git pull origin staging
```

### Paso 2: Realizar los cambios y ejecutar las pruebas automatizadas locales
Antes de subir cualquier modificación, ejecuta la suite de pruebas para confirmar que ningún flujo comercial (ventas, compras, créditos, recibos, inventario, finanzas) se haya roto:
```powershell
python -m pytest -v
```

### Paso 3: Guardar y enviar los cambios a `staging`
```powershell
git add .
git commit -m "feat: descripcion clara de la mejora implementada"
git push origin staging
```

### Paso 4: Validar en `citypet-testing` (Render)
1. Render detectará automáticamente el nuevo commit en la rama `staging`, instalará dependencias, ejecutará `flask sync-schema` y reiniciará `citypet-testing`.
2. Abre la URL de pruebas (`https://citypet-testing.onrender.com`) y verifica que aparezca la etiqueta amarilla **`ENTORNO DE PRUEBAS (STAGING)`** en la barra superior.
3. Comparte el enlace de `citypet-testing` con el cliente para que pruebe libremente las nuevas funciones usando datos de demostración, sin ningún riesgo para su contabilidad ni inventario real.

---

## 4. Paso a Paso para Promover Cambios Aprobados a PRODUCTION (`main`)

Una vez que el cambio fue validado en `citypet-testing` y aprobado por el cliente:

### Paso 1: Descargar un respaldo preventivo de Producción
Antes de actualizar `production`, ingresa como Propietario en `citypet-production` -> **Configuración (Engranaje) -> Respaldos y Restauración** y haz clic en **Exportar Respaldo Completo JSON** (`CityPet_FullBackup_production_*.json`).

### Paso 2: Fusionar `staging` dentro de `main`
```powershell
git checkout main
git pull origin main
git merge staging
```

### Paso 3: Verificar tests por última vez y publicar en `main`
```powershell
python -m pytest -v
git push origin main
```

### Paso 4: Verificación Post-Despliegue en `citypet-production`
1. Render desplegará automáticamente la rama `main` en el servicio `citypet-production` y ejecutará `flask sync-schema` (que añade cualquier tabla o columna nueva sin tocar los registros existentes).
2. Comprueba que `https://<tu-dominio-produccion>/health` devuelva `"status": "ok"` y `"environment": "production"`.
3. Regresa tu copia local a la rama `staging` para futuras tareas:
   ```powershell
   git checkout staging
   ```

---

## 5. Cómo Revertir un Cambio en Caso de Emergencia (Rollback de Código)

Si tras fusionar a `main` detectas un comportamiento inesperado en la interfaz o en una ruta:

```powershell
git checkout main
git revert HEAD --no-edit
git push origin main
```

Render desplegará inmediatamente la versión anterior estable sin alterar ningún dato almacenado en Supabase PostgreSQL.
