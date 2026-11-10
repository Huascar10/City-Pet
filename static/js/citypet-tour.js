/**
 * CityPet Interactive Guided Tour
 * Complete 25-module interactive walkthrough with role awareness.
 */

(function () {
  const TOUR_STEPS = [
    {
      id: 'step-brand',
      target: '.sidebar-brand',
      title: '1. Identidad de CityPet',
      content: 'Bienvenido a CityPet Pharma. Este es el sistema integral para gestión de inventario, comercialización y trazabilidad veterinaria.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-dashboard',
      target: 'a[href*="dashboard"]',
      title: '2. Panel de Control (Dashboard)',
      content: 'Accede a las métricas clave del negocio en tiempo real: ventas del período, utilidad bruta estimada, productos agotados y alertas operativas.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-pos',
      target: 'a[href*="/sales/pos"]',
      title: '3. Punto de Venta (POS)',
      content: 'Emite facturas y comprobantes con agilidad. Busca productos por código, nombre o código de barra, aplica descuentos y selecciona el cliente.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-preview',
      target: '#btnPreviewSale, #sidebarToggle',
      title: '4. Vista Previa de Recibos',
      content: 'Antes de guardar cualquier operación de venta o compra, puedes consultar una vista previa fidedigna con marca de agua para evitar errores.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-products',
      target: 'a[href*="/products"]',
      title: '5. Catálogo de Productos',
      content: 'Administra los medicamentos, insumos y alimentos para animales. Consulta precios de venta, categorías y estado de existencia.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-stock-status',
      target: 'a[href*="/products"]',
      title: '6. Alertas de Existencias',
      content: 'Visualiza rápidamente productos en estado "Ok", "Menor al Mínimo" o "Agotada" con indicadores por colores para reabastecimiento oportuno.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-inventory',
      target: 'a[href*="/inventory"]',
      title: '7. Control de Movimientos de Inventario',
      content: 'Registro cronológico y auditable de todas las entradas, salidas, mermas, regalías y transferencias de mercancía.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-physical-audit',
      target: 'a[href*="/inventory/audit"]',
      title: '8. Conteo Físico de Inventario',
      content: 'Compara el stock físico real contado en bodega contra el stock registrado en el sistema y aplica ajustes automáticos auditables.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-reconciliation',
      target: 'a[href*="/inventory/reconciliation"]',
      title: '9. Conciliación Matemática',
      content: 'Herramienta de precisión: valida que (Stock Inicial + Entradas - Salidas = Stock Teórico) coincida exactamente con las existencias actuales.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-purchases',
      target: 'a[href*="/purchases"]',
      title: '10. Compras a Proveedores',
      content: 'Registra el ingreso de mercancía de proveedores, actualiza costos de compra automáticamente y genera recibos de compra oficiales.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-sales-history',
      target: 'a[href*="/sales"]',
      title: '11. Historial de Ventas',
      content: 'Consulta el registro completo de facturas emitidas, estados de pago (Contado / Crédito) y detalles de productos vendidos.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-abonos',
      target: 'a[href*="/sales/abonos"]',
      title: '12. Cobranza y Abonos',
      content: 'Gestiona las cuentas por cobrar de ventas a crédito, emite recibos de abono y visualiza el saldo pendiente restante al instante.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-client-returns',
      target: 'a[href*="/inventory"]',
      title: '13. Devoluciones de Clientes',
      content: 'Reintegra mercancía devuelta por clientes con reembolso de dinero auditable o compensación de saldo.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-supplier-returns',
      target: 'a[href*="/inventory"]',
      title: '14. Devoluciones a Proveedores',
      content: 'Gestiona devoluciones de productos defectuosos o vencidos a proveedores con deducción de stock y recuperación financiera.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-clients',
      target: 'a[href*="/clients"]',
      title: '15. Directorio de Clientes',
      content: 'Base de datos de clínicas veterinarias, haciendas y clientes individuales con teléfonos, direcciones, RUC y límites de crédito.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-suppliers',
      target: 'a[href*="/suppliers"]',
      title: '16. Proveedores y Laboratorios',
      content: 'Información de laboratorios veterinarios y distribuidores autorizados (Novavet y otros) con historial de suministros.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-finances',
      target: 'a[href*="/finances"]',
      title: '17. Movimientos de Dinero',
      content: 'Control de caja chica, gastos operativos (alquiler, servicios, fletes) e ingresos extraordinarios con balance neto.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-receipts',
      target: 'a[href*="/receipts"]',
      title: '18. Comprobantes y Recibos Inmutables',
      content: 'Repositorio de todos los comprobantes emitidos. Permite reimprimir facturas formato oficial CityPet Pharma con pagaré legal.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-imports',
      target: 'a[href*="/imports"]',
      title: '19. Importación Inteligente Excel',
      content: 'Herramienta para importar inventarios masivos con mapeo visual de columnas y vista previa antes de guardar.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-reports',
      target: 'a[href*="/reports"]',
      title: '20. Reportes y Exportación',
      content: 'Exporta reportes analíticos de ventas e inventario a formatos Excel (.xlsx) y PDF de alta calidad con un solo clic.',
      roles: ['propietario', 'administrador', 'empleado']
    },
    {
      id: 'step-daily',
      target: 'a[href*="/reports/daily"]',
      title: '21. Resumen Diario de Operaciones',
      content: 'Cierre de caja y balance del día ajustado a la zona horaria de Nicaragua (UTC-6 Managua) con detalle de ventas, compras y abonos.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-monthly',
      target: 'a[href*="/reports/monthly"]',
      title: '22. Resumen Mensual & Comparativa MoM',
      content: 'Consolidado comercial del mes, cálculo de margen bruto, ticket promedio, % de crecimiento respecto al mes anterior y productos top.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-trends',
      target: 'a[href*="/reports/trends"]',
      title: '23. Tendencias Temporales',
      content: 'Gráficos evolutivos para 7 días, 30 días, 3 meses y rangos personalizados con comparativas de desempeño.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-appearance',
      target: 'a[href*="/settings/appearance"]',
      title: '24. Personalización y Logotipos',
      content: 'Configura el modo Claro/Oscuro/Sistema, elige entre paletas de color veterinarias o personalizadas y actualiza el logotipo del negocio.',
      roles: ['propietario', 'administrador']
    },
    {
      id: 'step-telegram-backups',
      target: 'a[href*="/settings/telegram"]',
      title: '25. Notificaciones Telegram & Respaldos',
      content: 'Recibe alertas inmediatas de ventas y stock crítico en tu celular vía Telegram y descarga respaldos completos de la base de datos.',
      roles: ['propietario']
    }
  ];

  let currentStepIdx = 0;
  let activeSteps = [];
  let overlayEl = null;
  let cardEl = null;

  function getUserRole() {
    const roleEl = document.querySelector('[data-user-role]');
    if (roleEl) return roleEl.getAttribute('data-user-role');
    const roleText = document.querySelector('.dropdown-toggle small');
    if (roleText) return roleText.textContent.trim().toLowerCase();
    return 'empleado';
  }

  function startTour() {
    const userRole = getUserRole();
    activeSteps = TOUR_STEPS.filter(s => s.roles.includes(userRole));
    currentStepIdx = 0;
    renderStep();
  }

  function renderStep() {
    cleanupTour();
    if (currentStepIdx < 0 || currentStepIdx >= activeSteps.length) {
      endTour();
      return;
    }

    const step = activeSteps[currentStepIdx];
    const targetEl = document.querySelector(step.target);

    // Overlay
    overlayEl = document.createElement('div');
    overlayEl.className = 'tour-overlay';
    document.body.appendChild(overlayEl);

    // Card
    cardEl = document.createElement('div');
    cardEl.className = 'tour-card shadow';
    cardEl.innerHTML = `
      <div class="d-flex justify-content-between align-items-center mb-2">
        <span class="badge bg-primary text-white" style="font-size: 0.75rem;">Paso ${currentStepIdx + 1} de ${activeSteps.length}</span>
        <button type="button" class="btn-close btn-sm" id="btnTourClose" aria-label="Cerrar"></button>
      </div>
      <h6 class="fw-bold mb-2">${step.title}</h6>
      <p class="small text-muted mb-3" style="line-height: 1.4;">${step.content}</p>
      <div class="d-flex justify-content-between align-items-center gap-2">
        <div>
          ${currentStepIdx > 0 ? '<button class="btn btn-outline-secondary btn-sm" id="btnTourPrev"><i class="bi bi-arrow-left"></i> Ant.</button>' : ''}
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-light btn-sm" id="btnTourSkip">Omitir</button>
          <button class="btn btn-primary btn-sm" id="btnTourNext">
            ${currentStepIdx === activeSteps.length - 1 ? 'Finalizar <i class="bi bi-check-lg"></i>' : 'Sig. <i class="bi bi-arrow-right"></i>'}
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(cardEl);

    if (targetEl) {
      targetEl.classList.add('tour-target-highlight');
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      positionCard(targetEl, cardEl);
    } else {
      // Center card if target not found
      cardEl.style.top = '50%';
      cardEl.style.left = '50%';
      cardEl.style.transform = 'translate(-50%, -50%)';
    }

    document.getElementById('btnTourClose').onclick = endTour;
    document.getElementById('btnTourSkip').onclick = endTour;
    document.getElementById('btnTourNext').onclick = () => {
      currentStepIdx++;
      renderStep();
    };
    const prevBtn = document.getElementById('btnTourPrev');
    if (prevBtn) {
      prevBtn.onclick = () => {
        currentStepIdx--;
        renderStep();
      };
    }
  }

  function positionCard(target, card) {
    const rect = target.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    let top = rect.bottom + 12;
    let left = rect.left;

    // Check bottom overflow
    if (top + 220 > window.innerHeight) {
      top = Math.max(10, rect.top - 230);
    }
    // Check right overflow
    if (left + 380 > window.innerWidth) {
      left = Math.max(10, window.innerWidth - 390);
    }

    card.style.top = `${Math.max(10, top)}px`;
    card.style.left = `${Math.max(10, left)}px`;
    card.style.transform = 'none';
  }

  function cleanupTour() {
    document.querySelectorAll('.tour-target-highlight').forEach(el => {
      el.classList.remove('tour-target-highlight');
    });
    if (overlayEl) {
      overlayEl.remove();
      overlayEl = null;
    }
    if (cardEl) {
      cardEl.remove();
      cardEl = null;
    }
  }

  function endTour() {
    cleanupTour();
    localStorage.setItem('citypet_tour_completed', 'true');
  }

  window.startCityPetTour = startTour;
})();
