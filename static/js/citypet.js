/**
 * CityPet Core UI Helpers
 * - Dynamic scrollable and collapsible sidebar with persistence (localStorage)
 * - Mobile responsive drawer with backdrop
 * - Product image lightbox modal with zoom controls
 * - Notification toasts
 */

const CityPetUI = {
  init: function () {
    this.restoreSidebarPreference();
    this.initTooltips();
    this.initAlerts();
  },

  restoreSidebarPreference: function () {
    const isCollapsed = localStorage.getItem('citypet_sidebar_collapsed') === 'true';
    if (window.innerWidth >= 992 && isCollapsed) {
      document.body.classList.add('sidebar-collapsed');
      const icon = document.getElementById('sidebarCollapseIcon');
      if (icon) icon.className = 'bi bi-chevron-bar-right fs-5';
    }
  },

  toggleSidebar: function () {
    if (window.innerWidth < 992) {
      // Mobile drawer toggle
      const sidebar = document.getElementById('sidebar-wrapper');
      const backdrop = document.getElementById('sidebarBackdrop');
      if (sidebar) {
        sidebar.classList.toggle('toggled');
        if (backdrop) {
          backdrop.classList.toggle('show', sidebar.classList.contains('toggled'));
        }
      }
    } else {
      // Desktop collapse toggle
      this.toggleSidebarCollapse();
    }
  },

  toggleSidebarCollapse: function () {
    const isNowCollapsed = document.body.classList.toggle('sidebar-collapsed');
    localStorage.setItem('citypet_sidebar_collapsed', isNowCollapsed ? 'true' : 'false');
    const icon = document.getElementById('sidebarCollapseIcon');
    if (icon) {
      icon.className = isNowCollapsed ? 'bi bi-chevron-bar-right fs-5' : 'bi bi-chevron-bar-left fs-5';
    }
  },

  closeMobileSidebar: function () {
    const sidebar = document.getElementById('sidebar-wrapper');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (sidebar) sidebar.classList.remove('toggled');
    if (backdrop) backdrop.classList.remove('show');
  },

  initTooltips: function () {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function (el) {
      new bootstrap.Tooltip(el, { trigger: 'hover' });
    });
  },

  initAlerts: function () {
    const autoAlerts = document.querySelectorAll('.alert-dismissible');
    autoAlerts.forEach(function (alert) {
      setTimeout(function () {
        const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
        if (bsAlert) bsAlert.close();
      }, 5000);
    });
  }
};

/**
 * Product Image Lightbox with Zoom Controls
 */
const CityPetLightbox = {
  currentScale: 1.0,
  minScale: 0.5,
  maxScale: 3.0,
  stepScale: 0.25,

  open: function (imageUrl, title, subtitle) {
    if (!imageUrl) return;
    const modalEl = document.getElementById('citypetImageLightboxModal');
    if (!modalEl) return;

    const img = document.getElementById('lightboxImg');
    const titleEl = document.getElementById('lightboxTitle');
    const subtitleEl = document.getElementById('lightboxSubtitle');

    if (img) img.src = imageUrl;
    if (titleEl) titleEl.textContent = title || 'Fotografía de Producto';
    if (subtitleEl) subtitleEl.textContent = subtitle || '';

    this.resetZoom();
    const bsModal = bootstrap.Modal.getOrCreateInstance(modalEl);
    bsModal.show();
  },

  zoomIn: function () {
    if (this.currentScale < this.maxScale) {
      this.currentScale = Math.min(this.maxScale, this.currentScale + this.stepScale);
      this.applyScale();
    }
  },

  zoomOut: function () {
    if (this.currentScale > this.minScale) {
      this.currentScale = Math.max(this.minScale, this.currentScale - this.stepScale);
      this.applyScale();
    }
  },

  resetZoom: function () {
    this.currentScale = 1.0;
    this.applyScale();
  },

  applyScale: function () {
    const img = document.getElementById('lightboxImg');
    const zoomText = document.getElementById('lightboxZoomLevel');
    if (img) {
      img.style.transform = `scale(${this.currentScale})`;
    }
    if (zoomText) {
      zoomText.textContent = `${Math.round(this.currentScale * 100)}%`;
    }
  }
};

// Global Toast helper
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toastEl = document.createElement('div');
  toastEl.className = `toast align-items-center text-white bg-${type} border-0 shadow`;
  toastEl.setAttribute('role', 'alert');
  toastEl.setAttribute('aria-live', 'assertive');
  toastEl.setAttribute('aria-atomic', 'true');

  toastEl.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
    </div>
  `;

  container.appendChild(toastEl);
  const bsToast = new bootstrap.Toast(toastEl, { delay: 4000 });
  bsToast.show();
  toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

document.addEventListener('DOMContentLoaded', function () {
  CityPetUI.init();
});
