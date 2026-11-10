import threading
import requests
import logging
from flask import current_app
from extensions import db
from models import SystemSetting
from services.crypto_service import CryptoService

logger = logging.getLogger(__name__)

class TelegramService:
    @staticmethod
    def save_bot_token(raw_token: str):
        """Encrypts and saves the Telegram bot token in SystemSetting."""
        clean = (raw_token or '').strip()
        if not clean:
            return
        # Ignore mask placeholder if submitted unchanged
        if set(clean) <= {'•', '*'}:
            return
        encrypted = CryptoService.encrypt_secret(clean)
        SystemSetting.set_val('telegram_bot_token', encrypted, "Token cifrado del bot de Telegram")

    @staticmethod
    def get_raw_stored_token() -> str:
        """Returns the raw value stored in SystemSetting (should start with ENCv1:)."""
        return SystemSetting.get_val('telegram_bot_token') or ''

    @staticmethod
    def ensure_token_encrypted() -> bool:
        """Ensures any legacy plaintext token in SystemSetting is encrypted at rest."""
        stored = SystemSetting.get_val('telegram_bot_token') or ''
        if stored and not CryptoService.is_encrypted(stored):
            encrypted = CryptoService.encrypt_secret(stored.strip())
            SystemSetting.set_val('telegram_bot_token', encrypted, "Token cifrado del bot de Telegram")
            return True
        return False

    @staticmethod
    def get_config():
        """Retrieve Telegram credentials (decrypting token in memory) and settings from DB or Config fallback."""
        stored_token = SystemSetting.get_val('telegram_bot_token') or ''
        if stored_token:
            # Auto-migrate legacy plaintext token to encrypted storage if found
            if not CryptoService.is_encrypted(stored_token):
                encrypted = CryptoService.encrypt_secret(stored_token.strip())
                SystemSetting.set_val('telegram_bot_token', encrypted, "Token cifrado del bot de Telegram")
                bot_token = stored_token.strip()
            else:
                try:
                    bot_token = CryptoService.decrypt_secret(stored_token).strip()
                except Exception:
                    bot_token = ''
        else:
            bot_token = (current_app.config.get('TELEGRAM_BOT_TOKEN') or '').strip()

        chat_id = (SystemSetting.get_val('telegram_chat_id') or current_app.config.get('TELEGRAM_CHAT_ID') or '').strip()
        default_enabled = 'true' if current_app.config.get('TELEGRAM_ENABLED', False) else 'false'
        raw_enabled = SystemSetting.get_val('telegram_enabled', default_enabled)
        enabled = (raw_enabled or default_enabled).lower() == 'true'
        if current_app.config.get('TELEGRAM_FORCE_DISABLED', False):
            enabled = False
        
        # Event notification toggles
        notify_sales = SystemSetting.get_val('telegram_notify_sales', 'true').lower() == 'true'
        notify_purchases = SystemSetting.get_val('telegram_notify_purchases', 'true').lower() == 'true'
        notify_inventory_in = SystemSetting.get_val('telegram_notify_in', 'true').lower() == 'true'
        notify_inventory_out = SystemSetting.get_val('telegram_notify_out', 'true').lower() == 'true'
        notify_finances = SystemSetting.get_val('telegram_notify_finances', 'true').lower() == 'true'
        notify_low_stock = SystemSetting.get_val('telegram_notify_low_stock', 'true').lower() == 'true'
        notify_out_stock = SystemSetting.get_val('telegram_notify_out_stock', 'true').lower() == 'true'

        return {
            'bot_token': bot_token,
            'has_token': bool(bot_token),
            'bot_token_masked': '••••••••••••••••••••••••' if bot_token else '',
            'chat_id': chat_id,
            'enabled': enabled,
            'notify_sales': notify_sales,
            'notify_purchases': notify_purchases,
            'notify_inventory_in': notify_inventory_in,
            'notify_inventory_out': notify_inventory_out,
            'notify_finances': notify_finances,
            'notify_low_stock': notify_low_stock,
            'notify_out_stock': notify_out_stock,
        }

    @staticmethod
    def send_raw_message(bot_token, chat_id, text):
        """Sends message via Telegram HTTP Bot API without exposing token in logs."""
        if not bot_token or not chat_id:
            return False, "Falta Token o Chat ID"
        try:
            app_env = current_app.config.get('APP_ENV', 'development')
            prod_chat_id = (current_app.config.get('PRODUCTION_TELEGRAM_CHAT_ID') or '').strip()
            if app_env == 'staging':
                if prod_chat_id and str(chat_id).strip() == prod_chat_id:
                    logger.warning("Intento bloqueado: STAGING intentó enviar mensaje al Chat ID de PRODUCCIÓN.")
                    return False, "Seguridad: El entorno STAGING no puede enviar notificaciones al Chat ID de PRODUCCIÓN."
                staging_prefix = "🧪 <b>[ENTORNO DE PRUEBAS - STAGING]</b>\n"
                if not str(text).startswith("🧪"):
                    text = f"{staging_prefix}{text}"
        except RuntimeError:
            # Outside Flask application context
            pass

        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }
            res = requests.post(url, json=payload, timeout=8)
            data = res.json()
            if res.status_code == 200 and data.get('ok'):
                return True, "Mensaje enviado exitosamente"
            return False, data.get('description', 'Error de Telegram')
        except Exception:
            logger.error("Error de red al conectar con el servidor de Telegram (credenciales protegidas).")
            return False, "No se pudo conectar con la API de Telegram."

    @classmethod
    def dispatch_async(cls, app, event_type, message_text):
        """Dispatches notification in background thread so commercial flow is never blocked."""
        if app.config.get('TESTING'):
            return
        def worker():
            with app.app_context():
                cfg = cls.get_config()
                if not cfg['enabled'] or not cfg['bot_token'] or not cfg['chat_id']:
                    return
                flag_key = f'notify_{event_type}'
                if flag_key in cfg and not cfg[flag_key]:
                    return
                cls.send_raw_message(cfg['bot_token'], cfg['chat_id'], message_text)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    @classmethod
    def notify_sale(cls, app, sale, receipt=None):
        currency = app.config.get('COMPANY_CURRENCY', 'C$')
        lines = [
            f"🛒 <b>NUEVA VENTA REGISTRADA — CITYPET PHARMA</b>",
            f"📄 <b>Factura:</b> #{sale.invoice_number}",
            f"👤 <b>Cliente:</b> {sale.client_name}",
            f"💼 <b>Vendedor:</b> {sale.salesperson or 'Mostrador'}",
            f"💳 <b>Condición:</b> {sale.payment_condition} ({sale.payment_method})",
            f"💵 <b>Total:</b> {currency} {sale.total:,.2f} (Pagado: {currency} {sale.paid_amount:,.2f} | Saldo: {currency} {sale.balance_due:,.2f})",
            "",
            "<b>Productos:</b>"
        ]
        for it in sale.items[:8]:
            lines.append(f" • {it.product_name_snapshot} x {it.quantity:.0f} = {currency} {it.total:,.2f}")
        if len(sale.items) > 8:
            lines.append(f" <i>...y {len(sale.items)-8} producto(s) más</i>")
            
        cls.dispatch_async(app, 'sales', "\n".join(lines))

    @classmethod
    def notify_purchase(cls, app, purchase, receipt=None):
        currency = app.config.get('COMPANY_CURRENCY', 'C$')
        lines = [
            f"📦 <b>NUEVA COMPRA REGISTRADA — CITYPET PHARMA</b>",
            f"📄 <b>Orden:</b> #{purchase.purchase_number} (Fact: {purchase.supplier_invoice_number or 'S/N'})",
            f"🏢 <b>Proveedor:</b> {purchase.supplier_name_snapshot}",
            f"💳 <b>Condición:</b> {purchase.payment_condition}",
            f"💵 <b>Total:</b> {currency} {purchase.total:,.2f} (Pagado: {currency} {purchase.paid_amount:,.2f} | Por pagar: {currency} {purchase.balance_due:,.2f})"
        ]
        cls.dispatch_async(app, 'purchases', "\n".join(lines))

    @classmethod
    def notify_payment(cls, app, payment, sale):
        currency = app.config.get('COMPANY_CURRENCY', 'C$')
        msg = (
            f"💰 <b>COBRO DE CRÉDITO RECIBIDO — CITYPET</b>\n"
            f"🧾 <b>Recibo:</b> #{payment.payment_number} (Factura #{sale.invoice_number})\n"
            f"👤 <b>Cliente:</b> {sale.client_name}\n"
            f"💵 <b>Abono:</b> {currency} {payment.amount:,.2f}\n"
            f"📊 <b>Saldo restante:</b> {currency} {payment.new_balance:,.2f}"
        )
        cls.dispatch_async(app, 'finances', msg)

    @classmethod
    def notify_supplier_payment(cls, app, supp_payment, purchase):
        currency = app.config.get('COMPANY_CURRENCY', 'C$')
        msg = (
            f"🏦 <b>PAGO A PROVEEDOR REGISTRADO — CITYPET</b>\n"
            f"🧾 <b>Comprobante:</b> #{supp_payment.payment_number} (Compra #{purchase.purchase_number})\n"
            f"🏢 <b>Proveedor:</b> {purchase.supplier_name_snapshot}\n"
            f"💸 <b>Importe pagado:</b> {currency} {supp_payment.amount:,.2f}\n"
            f"📊 <b>Saldo restante:</b> {currency} {supp_payment.new_balance:,.2f}"
        )
        cls.dispatch_async(app, 'finances', msg)

    @classmethod
    def notify_stock_alert(cls, app, product, alert_type):
        """alert_type: 'low_stock' or 'out_stock'"""
        if alert_type == 'out_stock':
            msg = (
                f"🚨 <b>ALERTA DE STOCK AGOTADO — CITYPET</b>\n"
                f"📦 <b>Producto:</b> {product.name} (<code>{product.code}</code>)\n"
                f"⚠️ <b>Existencias actuales:</b> 0 unidades\n"
                f"📋 <b>Stock Mínimo:</b> {product.min_stock:.0f} unidades"
            )
            cls.dispatch_async(app, 'out_stock', msg)
        else:
            msg = (
                f"⚠️ <b>ALERTA DE STOCK BAJO — CITYPET</b>\n"
                f"📦 <b>Producto:</b> {product.name} (<code>{product.code}</code>)\n"
                f"📉 <b>Existencias actuales:</b> {product.current_stock:.0f} unidades\n"
                f"📋 <b>Stock Mínimo:</b> {product.min_stock:.0f} unidades"
            )
            cls.dispatch_async(app, 'low_stock', msg)
