import os
import json
from datetime import datetime
from io import BytesIO
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, current_app, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import (
    SystemSetting, User, AuditLog, Product, Client, Supplier,
    Sale, SaleItem, Purchase, PurchaseItem, Payment, PurchasePayment,
    CreditException, InventoryMovement, FinancialMovement, Receipt
)
from routes.auth import owner_required, admin_required
from services.telegram_service import TelegramService
from services.backup_service import BackupService
from services.storage_service import StorageService, StorageValidationError

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

@settings_bp.route('/appearance', methods=['GET', 'POST'])
@login_required
@admin_required
def appearance():
    """
    Appearance, theme, custom color palette presets, and logo customization.
    """
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_theme':
            theme_mode = request.form.get('theme_mode', 'sistema')
            color_preset = request.form.get('color_preset', 'veterinario')
            primary_color = request.form.get('primary_color', '#1B4965')
            secondary_color = request.form.get('secondary_color', '#62B6CB')

            SystemSetting.set_val('theme_mode', theme_mode, "Modo de tema (claro, oscuro, sistema)")
            SystemSetting.set_val('color_preset', color_preset, "Preset de paleta")
            SystemSetting.set_val('theme_primary_color', primary_color, "Color primario personalizado")
            SystemSetting.set_val('theme_secondary_color', secondary_color, "Color secundario personalizado")

            # Check for logo uploads (validated & persisted via StorageService)
            if 'system_logo' in request.files:
                file = request.files['system_logo']
                if file and file.filename:
                    try:
                        logo_url = StorageService.save_logo_image(file, 'system')
                        SystemSetting.set_val('system_logo_url', logo_url, "Logotipo del sistema web")
                    except (StorageValidationError, RuntimeError) as exc:
                        flash(f"Error en logotipo del sistema: {exc}", "danger")
                        return redirect(url_for('settings.appearance'))

            if 'receipt_logo' in request.files:
                file = request.files['receipt_logo']
                if file and file.filename:
                    try:
                        rec_logo_url = StorageService.save_logo_image(file, 'receipt')
                        SystemSetting.set_val('receipt_logo_url', rec_logo_url, "Logotipo para recibos y facturas")
                    except (StorageValidationError, RuntimeError) as exc:
                        flash(f"Error en logotipo de recibos: {exc}", "danger")
                        return redirect(url_for('settings.appearance'))

            flash("Preferencias de apariencia y logotipos guardadas correctamente.", "success")
            return redirect(url_for('settings.appearance'))

        elif action == 'reset_logos':
            SystemSetting.set_val('system_logo_url', '/static/img/citypet_logo.png', "Logotipo del sistema web")
            SystemSetting.set_val('receipt_logo_url', '/static/img/citypet_logo_whitebg.png', "Logotipo para recibos")
            flash("Logotipos originales de CityPet Pharma restablecidos con éxito.", "info")
            return redirect(url_for('settings.appearance'))

        elif action == 'reset_palette':
            SystemSetting.set_val('theme_mode', 'sistema', "Modo de tema")
            SystemSetting.set_val('color_preset', 'veterinario', "Preset de color")
            SystemSetting.set_val('theme_primary_color', '#1B4965', "Color primario")
            SystemSetting.set_val('theme_secondary_color', '#62B6CB', "Color secundario")
            flash("Paleta de colores oficial restablecida a valores originales.", "info")
            return redirect(url_for('settings.appearance'))

    current_settings = {
        'theme_mode': SystemSetting.get_val('theme_mode', 'sistema'),
        'color_preset': SystemSetting.get_val('color_preset', 'veterinario'),
        'primary_color': SystemSetting.get_val('theme_primary_color', '#1B4965'),
        'secondary_color': SystemSetting.get_val('theme_secondary_color', '#62B6CB'),
        'system_logo_url': SystemSetting.get_val('system_logo_url', '/static/img/citypet_logo.png'),
        'receipt_logo_url': SystemSetting.get_val('receipt_logo_url', '/static/img/citypet_logo_whitebg.png')
    }

    return render_template('settings/appearance.html', settings=current_settings)

@settings_bp.route('/telegram', methods=['GET', 'POST'])
@login_required
@owner_required
def telegram():
    if request.method == 'POST':
        action = request.form.get('action')
        current_cfg = TelegramService.get_config()

        if action == 'test_connection':
            input_token = request.form.get('bot_token', '').strip()
            # If user left token blank or masked, use stored decrypted token
            if not input_token or '•' in input_token:
                test_token = current_cfg['bot_token']
            else:
                test_token = input_token
            test_chat_id = request.form.get('chat_id', '').strip() or current_cfg['chat_id']

            if not test_token or not test_chat_id:
                flash("Debe proporcionar Token y Chat ID para la prueba.", "warning")
                return redirect(url_for('settings.telegram'))

            msg = "✅ <b>CITYPET PHARMA</b> — Prueba de conexión con Telegram exitosa."
            success, err_msg = TelegramService.send_raw_message(test_token, test_chat_id, msg)
            if success:
                flash("¡Conexión con Telegram exitosa! Se ha enviado un mensaje de prueba al chat.", "success")
            else:
                flash(f"Error en la conexión con Telegram: {err_msg}", "danger")
            return redirect(url_for('settings.telegram'))

        # Save settings using encrypted storage for the bot token
        input_token = request.form.get('bot_token', '').strip()
        if input_token and '•' not in input_token:
            TelegramService.save_bot_token(input_token)
        elif request.form.get('clear_token') == '1':
            SystemSetting.set_val('telegram_bot_token', '', "Token del bot de Telegram (Cifrado)")

        SystemSetting.set_val('telegram_chat_id', request.form.get('chat_id', '').strip(), "Chat ID del canal o grupo de Telegram")
        SystemSetting.set_val('telegram_enabled', 'true' if request.form.get('enabled') else 'false', "Habilitar notificaciones")
        
        SystemSetting.set_val('telegram_notify_sales', 'true' if request.form.get('notify_sales') else 'false')
        SystemSetting.set_val('telegram_notify_purchases', 'true' if request.form.get('notify_purchases') else 'false')
        SystemSetting.set_val('telegram_notify_in', 'true' if request.form.get('notify_in') else 'false')
        SystemSetting.set_val('telegram_notify_out', 'true' if request.form.get('notify_out') else 'false')
        SystemSetting.set_val('telegram_notify_finances', 'true' if request.form.get('notify_finances') else 'false')
        SystemSetting.set_val('telegram_notify_low_stock', 'true' if request.form.get('notify_low_stock') else 'false')
        SystemSetting.set_val('telegram_notify_out_stock', 'true' if request.form.get('notify_out_stock') else 'false')

        audit = AuditLog(
            user_id=current_user.id,
            action='UPDATE_TELEGRAM_CONFIG',
            entity_type='SystemSetting',
            entity_id='telegram',
            details="Configuración de Telegram actualizada con almacenamiento cifrado de credenciales."
        )
        db.session.add(audit)
        db.session.commit()

        flash("Configuración de Telegram guardada de forma segura (Token cifrado en reposo).", "success")
        return redirect(url_for('settings.telegram'))

    # Ensure any legacy plaintext token in DB is migrated to encrypted format automatically
    TelegramService.ensure_token_encrypted()
    config = TelegramService.get_config()
    # Never pass the raw plaintext token to the HTML template
    safe_config = dict(config)
    safe_config['bot_token'] = ''
    return render_template('settings/telegram.html', config=safe_config)

@settings_bp.route('/users', methods=['GET', 'POST'])
@login_required
@owner_required
def users():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            username = request.form.get('username', '').strip()
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip() or None
            role = request.form.get('role', 'empleado')
            password = request.form.get('password', '')
            can_auth_credit = bool(request.form.get('can_authorize_credit')) or (role == 'propietario')

            if not username or not full_name or not password:
                flash("Complete todos los campos obligatorios.", "danger")
                return redirect(url_for('settings.users'))

            if User.query.filter_by(username=username).first():
                flash(f"El nombre de usuario '{username}' ya existe.", "danger")
                return redirect(url_for('settings.users'))

            new_user = User(
                username=username,
                full_name=full_name,
                email=email,
                role=role,
                is_active=True,
                can_authorize_credit=can_auth_credit
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            flash(f"Usuario '{username}' ({role.capitalize()}) creado exitosamente.", "success")
            return redirect(url_for('settings.users'))

        elif action == 'edit':
            user_id = request.form.get('user_id', type=int)
            u = User.query.get_or_404(user_id)
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip() or None
            role = request.form.get('role')
            can_auth_credit = bool(request.form.get('can_authorize_credit'))

            if full_name:
                u.full_name = full_name
            u.email = email
            
            # If changing role, verify not demoting last owner
            if role in ('propietario', 'administrador', 'empleado'):
                if u.role == 'propietario' and role != 'propietario':
                    owners_count = User.query.filter_by(role='propietario', is_active=True).count()
                    if owners_count <= 1:
                        flash("No puedes cambiar el rol del único propietario activo del sistema.", "warning")
                        return redirect(url_for('settings.users'))
                u.role = role

            u.can_authorize_credit = True if u.role == 'propietario' else can_auth_credit
            db.session.commit()
            flash(f"Usuario '{u.username}' actualizado correctamente.", "success")
            return redirect(url_for('settings.users'))

        elif action == 'unlock':
            user_id = request.form.get('user_id', type=int)
            u = User.query.get_or_404(user_id)
            u.failed_login_attempts = 0
            u.locked_until = None
            audit = AuditLog(
                user_id=current_user.id,
                action='UNLOCK_USER',
                entity_type='User',
                entity_id=str(u.id),
                details=f"Cuenta de '{u.username}' desbloqueada manualmente por {current_user.username}"
            )
            db.session.add(audit)
            db.session.commit()
            flash(f"Cuenta de '{u.username}' desbloqueada exitosamente.", "success")
            return redirect(url_for('settings.users'))

        elif action == 'reset_password':
            user_id = request.form.get('user_id', type=int)
            new_password = request.form.get('new_password', '')
            admin_confirmation = request.form.get('admin_confirmation', '')

            u = User.query.get_or_404(user_id)
            if not current_user.check_password(admin_confirmation):
                flash("Contraseña de confirmación del propietario incorrecta.", "danger")
                return redirect(url_for('settings.users'))

            if len(new_password) < 6:
                flash("La nueva contraseña debe tener al menos 6 caracteres.", "warning")
                return redirect(url_for('settings.users'))

            u.set_password(new_password)
            u.failed_login_attempts = 0
            u.locked_until = None
            db.session.commit()

            audit = AuditLog(
                user_id=current_user.id,
                action='RESET_PASSWORD',
                entity_type='User',
                entity_id=str(u.id),
                details=f"Contraseña de '{u.username}' restablecida por el propietario {current_user.username}"
            )
            db.session.add(audit)
            db.session.commit()

            flash(f"Contraseña de '{u.username}' restablecida exitosamente.", "success")
            return redirect(url_for('settings.users'))

        elif action == 'toggle_status':
            user_id = request.form.get('user_id', type=int)
            u = User.query.get_or_404(user_id)
            if u.id == current_user.id:
                flash("No puedes desactivar tu propia cuenta de usuario.", "warning")
            else:
                u.is_active = not u.is_active
                db.session.commit()
                flash(f"Estado de {u.username} actualizado a {'activo' if u.is_active else 'inactivo'}.", "info")
            return redirect(url_for('settings.users'))

    all_users = User.query.order_by(User.id.asc()).all()
    return render_template('settings/users.html', users=all_users)

@settings_bp.route('/backups', methods=['GET', 'POST'])
@login_required
@owner_required
def backups():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'export_json':
            snapshot = BackupService.generate_full_backup_dict(
                exported_by=current_user.username,
                include_media=True
            )

            buffer = BytesIO()
            buffer.write(json.dumps(snapshot, indent=2, ensure_ascii=False).encode('utf-8'))
            buffer.seek(0)
            
            audit = AuditLog(
                user_id=current_user.id,
                action='EXPORT_BACKUP',
                entity_type='Database',
                details=f"Exportación de respaldo relacional completo (SHA-256: {snapshot['metadata']['checksum_sha256'][:16]}...)"
            )
            db.session.add(audit)
            db.session.commit()

            env_tag = current_app.config.get('APP_ENV', 'development')
            filename = f"CityPet_FullBackup_{env_tag}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            return send_file(
                buffer,
                as_attachment=True,
                download_name=filename,
                mimetype='application/json'
            )

    last_audits = AuditLog.query.filter(
        AuditLog.action.in_(['EXPORT_BACKUP', 'CONTROLLED_DATABASE_RESET', 'RESTORE_BACKUP', 'VERIFY_BACKUP'])
    ).order_by(AuditLog.created_at.desc()).limit(15).all()
    return render_template('settings/backups.html', backup_logs=last_audits)

@settings_bp.route('/verify-backup', methods=['POST'])
@login_required
@owner_required
def verify_backup():
    """
    Verifies a backup JSON file by restoring it into an isolated in-memory test database
    and checking all table counts and SHA-256 checksum without altering live data.
    """
    if 'backup_file' not in request.files:
        flash("No se seleccionó ningún archivo para verificar.", "warning")
        return redirect(url_for('settings.backups'))

    file = request.files['backup_file']
    if not file or not file.filename.endswith('.json'):
        flash("El archivo debe tener formato .json válido.", "danger")
        return redirect(url_for('settings.backups'))

    try:
        data = json.load(file)
        ok, verify_msg, counts = BackupService.verify_backup_in_isolated_db(data)
        if ok:
            audit = AuditLog(
                user_id=current_user.id,
                action='VERIFY_BACKUP',
                entity_type='Database',
                details=f"Verificación aislada exitosa de {file.filename}: {verify_msg}"
            )
            db.session.add(audit)
            db.session.commit()
            flash(f"✅ Verificación en base de datos aislada exitosa: {verify_msg}", "success")
        else:
            flash(f"❌ La verificación del respaldo falló: {verify_msg}", "danger")
    except Exception as e:
        flash(f"Error al verificar el archivo de respaldo: {str(e)}", "danger")

    return redirect(url_for('settings.backups'))

@settings_bp.route('/reset-database', methods=['POST'])
@login_required
@owner_required
def reset_database():
    """
    Controlled Database Reset with Multi-step verification:
    1. Confirmation phrase match: 'BORRAR DATOS OPERATIVOS' or 'CONFIRMAR REINICIO'
    2. Owner password re-authentication
    3. Mandatory automated full relational backup with verified integrity
    4. Mandatory verified Telegram notification (FAILSAFE: aborts if Telegram fails or bot offline)
    5. Controlled selective wipe: deletes operational tables while strictly preserving User and SystemSetting
    """
    phrase = request.form.get('confirmation_phrase', '').strip()
    password = request.form.get('password', '').strip()

    valid_phrases = {'BORRAR DATOS OPERATIVOS', 'CONFIRMAR REINICIO'}
    if phrase not in valid_phrases:
        flash("Reinicio cancelado: La frase de confirmación escrita no coincide exactamente con 'BORRAR DATOS OPERATIVOS'.", "danger")
        return redirect(url_for('settings.backups'))

    if not current_user.check_password(password):
        flash("Reinicio cancelado: Contraseña de Propietario incorrecta. Verificación de identidad fallida.", "danger")
        return redirect(url_for('settings.backups'))

    backups_dir = os.path.join(current_app.root_path, 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    backup_filename = f"auto_backup_before_reset_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    backup_path = os.path.join(backups_dir, backup_filename)

    try:
        snapshot = BackupService.save_backup_file(backup_path, exported_by=current_user.username)
        is_valid, val_msg = BackupService.verify_backup_payload(snapshot)
        if not is_valid:
            raise ValueError(val_msg)
    except Exception as e:
        flash(f"Reinicio cancelado por salvaguarda: No fue posible generar el respaldo previo de seguridad ({str(e)}).", "danger")
        return redirect(url_for('settings.backups'))

    tg_config = TelegramService.get_config()
    if not tg_config['enabled'] or not tg_config['bot_token'] or not tg_config['chat_id']:
        flash("Reinicio CANCELADO por protocolo de seguridad: El bot de Telegram no está configurado o no está habilitado. El reinicio controlado exige verificación de notificación por Telegram obligatoria.", "danger")
        return redirect(url_for('settings.backups'))

    alert_text = (
        f"🚨 <b>ALERTA CRÍTICA DE SEGURIDAD — CITYPET PHARMA</b>\n"
        f"⚠️ <b>Acción:</b> Solicitud de Reinicio Controlado de Base de Datos\n"
        f"👤 <b>Usuario Propietario:</b> {current_user.full_name} (@{current_user.username})\n"
        f"🕒 <b>Fecha/Hora:</b> {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S')} UTC\n"
        f"💾 <b>Respaldo Previo Verificado:</b> {backup_filename}\n"
        f"🛡️ <b>Estado:</b> Notificación entregada con éxito. Ejecutando reinicio de tablas operativas."
    )
    tg_success, tg_msg = TelegramService.send_raw_message(tg_config['bot_token'], tg_config['chat_id'], alert_text)
    if not tg_success:
        flash(f"Reinicio CANCELADO por salvaguarda: La notificación de seguridad a Telegram no pudo entregarse ({tg_msg}). La base de datos no fue modificada.", "danger")
        return redirect(url_for('settings.backups'))

    try:
        db.session.query(Receipt).delete()
        db.session.query(FinancialMovement).delete()
        db.session.query(InventoryMovement).delete()
        db.session.query(Payment).delete()
        db.session.query(SaleItem).delete()
        db.session.query(CreditException).delete()
        db.session.query(Sale).delete()
        db.session.query(PurchasePayment).delete()
        db.session.query(PurchaseItem).delete()
        db.session.query(Purchase).delete()

        for p in Product.query.all():
            p.current_stock = 0.0
            p.physical_stock = 0.0

        audit = AuditLog(
            user_id=current_user.id,
            action='CONTROLLED_DATABASE_RESET',
            entity_type='Database',
            details=f"Reinicio controlado ejecutado exitosamente por {current_user.username}. Respaldo previo: {backup_filename}. Alerta Telegram confirmada."
        )
        db.session.add(audit)
        db.session.commit()

        flash("Reinicio de datos operativos completado exitosamente. Se ha generado un respaldo íntegro y se ha enviado la notificación de seguridad a Telegram.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al ejecutar reinicio de base de datos: {str(e)}", "danger")

    return redirect(url_for('settings.backups'))

@settings_bp.route('/restore-backup', methods=['POST'])
@login_required
@owner_required
def restore_backup():
    """
    Restores the complete relational database (all 16 tables + media files)
    after verifying the backup in an isolated in-memory database first.
    """
    if 'backup_file' not in request.files:
        flash("No se seleccionó ningún archivo de respaldo.", "warning")
        return redirect(url_for('settings.backups'))

    file = request.files['backup_file']
    if not file or not file.filename.endswith('.json'):
        flash("El archivo debe tener formato .json válido.", "danger")
        return redirect(url_for('settings.backups'))

    try:
        data = json.load(file)
        # First verify in isolated DB before touching live DB
        ok, verify_msg, _ = BackupService.verify_backup_in_isolated_db(data)
        if not ok:
            flash(f"Restauración cancelada por seguridad: El archivo no superó la prueba aislada ({verify_msg}).", "danger")
            return redirect(url_for('settings.backups'))

        # Create automatic pre-restore safety backup
        backups_dir = os.path.join(current_app.root_path, 'backups')
        os.makedirs(backups_dir, exist_ok=True)
        pre_restore_file = os.path.join(backups_dir, f"auto_pre_restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json")
        BackupService.save_backup_file(pre_restore_file, exported_by=current_user.username)

        summary = BackupService.restore_full_backup(
            data,
            restored_by_user_id=current_user.id,
            clear_existing=True,
            restore_media=True
        )

        flash(
            f"Restauración relacional completa exitosa desde {file.filename}: "
            f"{summary.get('products', 0)} productos, {summary.get('clients', 0)} clientes, "
            f"{summary.get('suppliers', 0)} proveedores, {summary.get('sales', 0)} ventas, "
            f"{summary.get('purchases', 0)} compras, {summary.get('inventory_movements', 0)} movimientos de inventario, "
            f"{summary.get('financial_movements', 0)} movimientos financieros y {summary.get('receipts', 0)} comprobantes restaurados.",
            "success"
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Error al procesar el archivo de restauración: {str(e)}", "danger")

    return redirect(url_for('settings.backups'))

@settings_bp.route('/audit')
@login_required
@owner_required
def audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template('settings/audit.html', logs=logs)
