/**
 * CityPet Step-by-Step Interactive Window Tutorials & Isolated Practice Mode (Section 12)
 * - Highlights real DOM elements on the active window
 * - Step progress counter ("Paso X de Y")
 * - Controls: Anterior, Siguiente, Omitir, Finalizar
 * - Isolated Practice Mode (Modo Práctica) that intercepts write operations so real data is never altered
 */

const CityPetInteractiveTour = {
  isDemoMode: false,
  activeSteps: [],
  currentStepIdx: 0,
  highlightedEl: null,

  init: function () {
    this.isDemoMode = sessionStorage.getItem('citypet_demo_mode') === 'true';
    this.injectStyles();
    this.updateDemoModeUI();
    this.setupPracticeInterception();
  },

  injectStyles: function () {
    if (document.getElementById('citypetInteractiveTourStyles')) return;
    const style = document.createElement('style');
    style.id = 'citypetInteractiveTourStyles';
    style.textContent = `
      .citypet-tour-highlight {
        position: relative !important;
        z-index: 1065 !important;
        box-shadow: 0 0 0 4px #FFB703, 0 0 24px rgba(15, 91, 158, 0.45) !important;
        border-radius: 8px !important;
        transition: box-shadow 0.25s ease !important;
      }
      .citypet-step-popover {
        position: fixed;
        bottom: 24px;
        right: 24px;
        width: 380px;
        max-width: calc(100vw - 32px);
        background: #ffffff;
        color: #1e293b;
        border-radius: 14px;
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.28);
        border: 2px solid #0F5B9E;
        z-index: 1080;
        padding: 18px;
      }
      [data-bs-theme="dark"] .citypet-step-popover {
        background: #1e293b;
        color: #f8fafc;
        border-color: #38bdf8;
      }
    `;
    document.head.appendChild(style);
  },

  toggleDemoMode: function (forceState) {
    if (typeof forceState === 'boolean') {
      this.isDemoMode = forceState;
    } else {
      this.isDemoMode = !this.isDemoMode;
    }

    sessionStorage.setItem('citypet_demo_mode', this.isDemoMode ? 'true' : 'false');
    this.updateDemoModeUI();

    if (typeof showToast === 'function') {
      if (this.isDemoMode) {
        showToast('🛡️ Modo Práctica ACTIVADO: Puedes ensayar ventas, compras, abonos y ajustes sin alterar datos reales.', 'warning');
      } else {
        showToast('✅ Modo Práctica DESACTIVADO: Estás de vuelta en el entorno comercial real.', 'info');
      }
    }
  },

  updateDemoModeUI: function () {
    const banner = document.getElementById('citypetDemoBanner');
    const btn = document.getElementById('btnToggleDemoMode');
    const btnText = document.getElementById('demoModeBtnText');

    if (banner) {
      banner.classList.toggle('d-none', !this.isDemoMode);
    }

    if (btn) {
      if (this.isDemoMode) {
        btn.classList.remove('btn-outline-warning');
        btn.classList.add('btn-warning', 'text-dark', 'fw-bold');
        if (btnText) btnText.textContent = 'Práctica Activa';
      } else {
        btn.classList.remove('btn-warning', 'text-dark', 'fw-bold');
        btn.classList.add('btn-outline-warning');
        if (btnText) btnText.textContent = 'Modo Práctica';
      }
    }
  },

  /**
   * Returns the step-by-step interactive tutorial definition for the current window (Section 12.1)
   */
  getStepsForCurrentWindow: function () {
    const path = window.location.pathname.toLowerCase();

    if (path.includes('/sales/pos')) {
      return {
        moduleTitle: 'Tutorial: Punto de Venta (POS)',
        steps: [
          {
            selector: '#productSearchInput',
            title: '1. Buscar y agregar productos',
            text: 'Escribe el nombre, código (ej. CP000001) o escanea el código de barras. Haz clic en el producto para añadirlo al carrito.'
          },
          {
            selector: '#cartTableBody',
            title: '2. Ajustar cantidades y descuentos',
            text: 'Aquí puedes modificar la cantidad a vender, el precio unitario o aplicar un porcentaje de descuento por línea.'
          },
          {
            selector: '#clientSelect',
            title: '3. Seleccionar cliente y revisar su crédito',
            text: 'Al elegir un cliente, verás inmediatamente su Límite de Crédito, Deuda Actual, Crédito Disponible y Facturas Vencidas.'
          },
          {
            selector: '#paymentConditionSelect',
            title: '4. Condición Contado o Crédito',
            text: 'Si eliges Crédito, podrás indicar el Abono Inicial y la Fecha de Vencimiento. Si excede el cupo, se solicitará autorización de supervisor.'
          },
          {
            selector: '#submitSaleBtn',
            title: '5. Emitir factura oficial',
            text: 'Pulsa "Vista Previa" para simular el documento o "Completar Venta" para emitir la factura, descontar stock y generar el recibo.'
          }
        ]
      };
    }

    if (path.includes('/sales/abonos')) {
      return {
        moduleTitle: 'Tutorial: Cobros y Abonos de Clientes',
        steps: [
          {
            selector: '#abonoTabs',
            title: '1. Cartera de créditos e historial',
            text: 'Alterna entre las facturas a crédito pendientes de cobro y el historial de recibos de abono emitidos.'
          },
          {
            selector: '#pending-pane',
            title: '2. Estado de cada factura',
            text: 'Observa el Total, lo Abonado, el Saldo Pendiente y el estado (Pendiente, Abonado, Vencida o Liquidado).'
          },
          {
            selector: '#pending-pane .btn-citypet-primary',
            title: '3. Registrar un abono parcial o total',
            text: 'Haz clic en "Registrar Abono" para ingresar el monto pagado. El saldo disminuirá automáticamente y al llegar a C$ 0 pasará a Liquidado.'
          }
        ]
      };
    }

    if (path.includes('/purchases/new')) {
      return {
        moduleTitle: 'Tutorial: Registrar Compra a Proveedor',
        steps: [
          {
            selector: '#supplierSelect',
            title: '1. Seleccionar proveedor (Novavet / CampoVet)',
            text: 'Elige el laboratorio o proveedor y anota el número de factura física entregada.'
          },
          {
            selector: '#paymentCondition',
            title: '2. Compra de Contado o a Crédito',
            text: 'Si seleccionas Crédito, podrás indicar cuánto pagas hoy y cuándo vence la factura. Solo el monto pagado hoy saldrá de Caja.'
          },
          {
            selector: '#purchaseItemsTable',
            title: '3. Productos recibidos y costos',
            text: 'Agrega los productos recibidos, sus cantidades y costos unitarios. Al confirmar, el stock subirá automáticamente.'
          },
          {
            selector: '#lblTotal',
            title: '4. Confirmar recepción y cuenta por pagar',
            text: 'Verifica el total y confirma la compra para generar el movimiento de entrada y el comprobante oficial.'
          }
        ]
      };
    }

    if (path.includes('/purchases')) {
      return {
        moduleTitle: 'Tutorial: Compras y Cuentas por Pagar',
        steps: [
          {
            selector: '.metric-card',
            title: '1. Resumen de Cuentas por Pagar',
            text: 'Consulta de un vistazo el total comprado, el monto efectivamente pagado y la deuda pendiente con proveedores.'
          },
          {
            selector: '.citypet-table',
            title: '2. Estado de pago de cada compra',
            text: 'Cada orden muestra su Total, Pagado, Saldo por Pagar y su estado (Pendiente, Abonado o Liquidado).'
          },
          {
            selector: '.btn-success, .btn-citypet-primary',
            title: '3. Pagar a proveedor o registrar compra',
            text: 'Usa el botón "Pagar" en cualquier compra a crédito para abonar o liquidar la deuda con el proveedor.'
          }
        ]
      };
    }

    if (path.includes('/products') || path.includes('/inventory')) {
      return {
        moduleTitle: 'Tutorial: Inventario y Conciliación',
        steps: [
          {
            selector: '.citypet-card',
            title: '1. Búsqueda y filtros rápidos',
            text: 'Filtra productos por categoría, proveedor o estado de stock (En Existencia, Menor al Mínimo o Agotada).'
          },
          {
            selector: '.citypet-table',
            title: '2. Existencias reales y trazabilidad',
            text: 'Cada producto muestra su stock actual, stock mínimo, conteo físico y acceso directo a su Kardex de movimientos.'
          }
        ]
      };
    }

    if (path.includes('/clients')) {
      return {
        moduleTitle: 'Tutorial: Clientes y Control de Crédito',
        steps: [
          {
            selector: '.citypet-card',
            title: '1. Filtros de cartera y ubicación',
            text: 'Busca clientes por nombre o razón social y filtra rápidamente quiénes tienen deuda activa o facturas vencidas.'
          },
          {
            selector: '.citypet-table',
            title: '2. Límite de crédito y perfil unificado',
            text: 'Haz clic en "Perfil" o en el nombre del cliente para ver sus facturas pendientes, abonos, liquidaciones y recibos.'
          }
        ]
      };
    }

    if (path.includes('/suppliers')) {
      return {
        moduleTitle: 'Tutorial: Proveedores y Deudas',
        steps: [
          {
            selector: '.citypet-card',
            title: '1. Directorio de proveedores',
            text: 'Filtra proveedores con saldo pendiente por pagar o compras vencidas.'
          },
          {
            selector: '.citypet-table',
            title: '2. Estado de cuenta del proveedor',
            text: 'Ingresa a "Perfil y Deudas" para consultar todas las compras realizadas al proveedor, pagos aplicados y saldo pendiente.'
          }
        ]
      };
    }

    return {
      moduleTitle: 'Tutorial: Panel Principal CityPet',
      steps: [
        {
          selector: '#quickActionsBar',
          title: '1. Acciones rápidas del negocio',
          text: 'Inicia una Nueva Venta, Nueva Compra, Abono de Cliente, Pago a Proveedor o consulta el Inventario con un solo clic.'
        },
        {
          selector: '.metric-card',
          title: '2. Indicadores diarios y dinero en caja',
          text: 'Monitorea Ventas del día, Cobros recibidos, Compras, Gastos adicionales y el Dinero Disponible sin doble conteo.'
        },
        {
          selector: '#sidebar-wrapper',
          title: '3. Menú simplificado en 7 secciones',
          text: 'Navega con claridad entre Inicio, Ventas, Compras, Inventario, Clientes, Proveedores y Reportes.'
        },
        {
          selector: '#settingsGearMenuBtn, #btnToggleDemoMode',
          title: '4. Modo Práctica y Configuración',
          text: 'Activa el "Modo Práctica" para entrenar sin afectar datos reales, o usa el icono de engranaje para Respaldos, Usuarios y Telegram.'
        }
      ]
    };
  },

  showWindowGuide: function () {
    const def = this.getStepsForCurrentWindow();
    this.activeSteps = def.steps || [];
    this.moduleTitle = def.moduleTitle || 'Tutorial de esta ventana';
    this.currentStepIdx = 0;
    this.renderCurrentStep();
  },

  clearHighlight: function () {
    if (this.highlightedEl) {
      this.highlightedEl.classList.remove('citypet-tour-highlight');
      this.highlightedEl = null;
    }
  },

  renderCurrentStep: function () {
    this.clearHighlight();
    let pop = document.getElementById('citypetStepPopover');
    if (!pop) {
      pop = document.createElement('div');
      pop.id = 'citypetStepPopover';
      pop.className = 'citypet-step-popover';
      document.body.appendChild(pop);
    }

    const total = this.activeSteps.length;
    if (total === 0 || this.currentStepIdx >= total) {
      this.closeGuide();
      return;
    }

    const step = this.activeSteps[this.currentStepIdx];
    if (step.selector) {
      const target = document.querySelector(step.selector);
      if (target) {
        this.highlightedEl = target;
        target.classList.add('citypet-tour-highlight');
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }

    const isFirst = this.currentStepIdx === 0;
    const isLast = this.currentStepIdx === total - 1;
    const pct = Math.round(((this.currentStepIdx + 1) / total) * 100);

    pop.innerHTML = `
      <div class="d-flex justify-content-between align-items-center mb-2">
        <span class="badge bg-primary">${this.moduleTitle}</span>
        <span class="small fw-bold text-muted">Paso ${this.currentStepIdx + 1} de ${total}</span>
      </div>
      <div class="progress mb-3" style="height: 6px;">
        <div class="progress-bar bg-warning" role="progressbar" style="width: ${pct}%;"></div>
      </div>
      <h6 class="fw-bold mb-1 text-primary">${step.title}</h6>
      <p class="small text-secondary mb-3">${step.text}</p>
      <div class="d-flex justify-content-between align-items-center pt-2 border-top">
        <button type="button" class="btn btn-sm btn-link text-muted p-0 text-decoration-none" onclick="CityPetInteractiveTour.closeGuide()">
          Omitir
        </button>
        <div class="d-flex gap-1">
          <button type="button" class="btn btn-sm btn-outline-secondary" ${isFirst ? 'disabled' : ''} onclick="CityPetInteractiveTour.prevStep()">
            <i class="bi bi-arrow-left"></i> Anterior
          </button>
          ${isLast
            ? `<button type="button" class="btn btn-sm btn-success fw-bold" onclick="CityPetInteractiveTour.closeGuide()"><i class="bi bi-check-lg"></i> Finalizar</button>`
            : `<button type="button" class="btn btn-sm btn-primary fw-bold" onclick="CityPetInteractiveTour.nextStep()">Siguiente <i class="bi bi-arrow-right"></i></button>`
          }
        </div>
      </div>
    `;
  },

  nextStep: function () {
    if (this.currentStepIdx < this.activeSteps.length - 1) {
      this.currentStepIdx++;
      this.renderCurrentStep();
    } else {
      this.closeGuide();
    }
  },

  prevStep: function () {
    if (this.currentStepIdx > 0) {
      this.currentStepIdx--;
      this.renderCurrentStep();
    }
  },

  closeGuide: function () {
    this.clearHighlight();
    const pop = document.getElementById('citypetStepPopover');
    if (pop) pop.remove();
  },

  /**
   * Intercepts POST forms and POS fetch calls when Practice Mode (isDemoMode) is active
   * so training never modifies real database records (Section 12.2).
   */
  setupPracticeInterception: function () {
    const self = this;

    // Intercept standard form submissions
    document.addEventListener('submit', function (e) {
      const form = e.target;
      if (!form || !self.isDemoMode) return;
      const method = (form.method || 'GET').toUpperCase();
      if (method === 'POST') {
        e.preventDefault();
        e.stopPropagation();
        self.showPracticeSimulationModal('Operación Simulada en Modo Práctica', 'El formulario fue validado correctamente en el entorno de práctica. Ningún registro real fue modificado en la base de datos.');
      }
    }, true);

    // Intercept fetch POST requests to /sales/create in Practice Mode
    const origFetch = window.fetch;
    window.fetch = function (url, options) {
      if (self.isDemoMode && typeof url === 'string' && url.includes('/sales/create') && options && options.method === 'POST') {
        self.showPracticeSimulationModal('Factura Emitida en Modo Práctica', 'La venta fue simulada exitosamente en memoria. El inventario, la caja y la deuda del cliente reales permanecen intactos.');
        return Promise.resolve(new Response(JSON.stringify({
          success: false,
          practice_simulated: true,
          error: 'Simulación completada en Modo Práctica (Sin cambios en base de datos real).'
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
      }
      return origFetch.apply(this, arguments);
    };
  },

  showPracticeSimulationModal: function (title, message) {
    let prev = document.getElementById('demoSaleSuccessModal');
    if (prev) prev.remove();

    const modalHtml = `
      <div class="modal fade" id="demoSaleSuccessModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content border-0 shadow-lg">
            <div class="modal-header bg-warning text-dark">
              <h5 class="modal-title fw-bold"><i class="bi bi-shield-check me-2"></i> ${title}</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body p-4 text-center">
              <i class="bi bi-check-circle-fill text-success fs-1 mb-2 d-block"></i>
              <p class="text-secondary small mb-0">${message}</p>
            </div>
            <div class="modal-footer justify-content-center">
              <button type="button" class="btn btn-primary btn-sm px-4" data-bs-dismiss="modal">Entendido</button>
            </div>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    new bootstrap.Modal(document.getElementById('demoSaleSuccessModal')).show();
  }
};

document.addEventListener('DOMContentLoaded', function () {
  CityPetInteractiveTour.init();
});
