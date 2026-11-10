from functools import wraps
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User, AuditLog, LoginAttempt

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 5
IP_WINDOW_MINUTES = 10
MAX_IP_FAILED_ATTEMPTS = 8

def owner_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_owner:
            flash("Acceso restringido: Se requieren privilegios de Propietario.", "danger")
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Acceso restringido: Se requieren privilegios de Administrador o Propietario.", "danger")
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def employee_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        ip_addr = request.remote_addr or '127.0.0.1'
        now = datetime.utcnow()

        # 1. Check IP-based brute force window
        window_start = now - timedelta(minutes=IP_WINDOW_MINUTES)
        recent_ip_failures = LoginAttempt.query.filter(
            LoginAttempt.ip_address == ip_addr,
            LoginAttempt.success == False,
            LoginAttempt.created_at >= window_start
        ).count()

        user = User.query.filter_by(username=username).first()

        # 2. Check User account lockout
        if user and user.locked_until and user.locked_until > now:
            remaining_sec = int((user.locked_until - now).total_seconds())
            remaining_min = max(1, (remaining_sec + 59) // 60)
            flash(
                f"Cuenta bloqueada temporalmente por seguridad tras múltiples intentos fallidos. "
                f"Intente nuevamente en {remaining_min} minuto(s).",
                "danger"
            )
            return render_template('auth/login.html'), 429

        if recent_ip_failures >= MAX_IP_FAILED_ATTEMPTS:
            flash(
                f"Demasiados intentos fallidos desde esta dirección ({ip_addr}). "
                f"Por seguridad, espere {LOCKOUT_DURATION_MINUTES} minutos antes de volver a intentar.",
                "danger"
            )
            return render_template('auth/login.html'), 429

        if user and user.check_password(password):
            if not user.is_active:
                flash("Su cuenta ha sido desactivada. Comuníquese con el propietario.", "danger")
                return render_template('auth/login.html'), 403

            # Reset failed attempts on success
            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_login = now

            attempt = LoginAttempt(ip_address=ip_addr, username=username, success=True, created_at=now)
            db.session.add(attempt)

            session.permanent = True
            login_user(user, remember=remember)

            audit = AuditLog(
                user_id=user.id,
                user_name=user.full_name,
                action='LOGIN',
                entity_type='User',
                entity_id=str(user.id),
                details=f"Inicio de sesión exitoso desde {ip_addr}",
                ip_address=ip_addr
            )
            db.session.add(audit)
            db.session.commit()

            flash(f"¡Bienvenido, {user.full_name}!", "success")
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.index'))
        else:
            # Record failed attempt
            attempt = LoginAttempt(ip_address=ip_addr, username=username, success=False, created_at=now)
            db.session.add(attempt)

            if user:
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                    user.locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                    audit_lock = AuditLog(
                        user_id=user.id,
                        user_name=user.username,
                        action='LOGIN_LOCKED',
                        entity_type='User',
                        entity_id=str(user.id),
                        details=f"Cuenta '{user.username}' bloqueada por {LOCKOUT_DURATION_MINUTES} min tras {user.failed_login_attempts} intentos fallidos desde {ip_addr}.",
                        ip_address=ip_addr
                    )
                    db.session.add(audit_lock)
                    db.session.commit()
                    flash(
                        f"Se alcanzó el límite de {MAX_FAILED_ATTEMPTS} intentos fallidos. "
                        f"La cuenta ha sido bloqueada por {LOCKOUT_DURATION_MINUTES} minutos.",
                        "danger"
                    )
                    return render_template('auth/login.html'), 429

            db.session.commit()
            flash("Usuario o contraseña incorrectos. Verifique sus credenciales.", "danger")
            return render_template('auth/login.html'), 401

    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    audit = AuditLog(
        user_id=current_user.id,
        user_name=current_user.full_name,
        action='LOGOUT',
        entity_type='User',
        entity_id=str(current_user.id),
        details="Cierre de sesión",
        ip_address=request.remote_addr
    )
    db.session.add(audit)
    db.session.commit()

    logout_user()
    session.clear()
    flash("Ha cerrado sesión correctamente.", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if full_name:
            current_user.full_name = full_name
        if email:
            current_user.email = email

        if new_password:
            if not current_password or not current_user.check_password(current_password):
                flash("La contraseña actual no es correcta.", "danger")
                return render_template('auth/profile.html')
            if new_password != confirm_password:
                flash("Las contraseñas nuevas no coinciden.", "danger")
                return render_template('auth/profile.html')
            if len(new_password) < 6:
                flash("La nueva contraseña debe tener al menos 6 caracteres.", "warning")
                return render_template('auth/profile.html')
            current_user.set_password(new_password)
            flash("Contraseña actualizada con éxito.", "success")

        db.session.commit()
        flash("Perfil actualizado correctamente.", "success")
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html')
