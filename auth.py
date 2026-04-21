from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app import db, bcrypt, csrf
from app.models import User, UserRole, AuditLog
from app.forms import (
    RegistrationForm, LoginForm, TwoFactorForm,
    ResetPasswordRequestForm, ResetPasswordForm
)
from app.decorators import buyer_required, admin_required
import os
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature


def send_email_code(to_email, code):
    sender = os.getenv("MAIL_EMAIL")
    password = os.getenv("MAIL_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = "Подтверждение регистрации"

    body = f"""
Здравствуйте!

Ваш код подтверждения: {code}

Код действует 10 минут.

Если вы не регистрировались — проигнорируйте это письмо.
"""
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, password)
        server.sendmail(sender, to_email, msg.as_string())
        server.quit()
        print(f"✅ Код подтверждения успешно отправлен на {to_email}")
    except Exception as e:
        print(f"❌ SMTP ошибка при отправке кода: {e}")
        # Можно добавить flash только для разработки
        # flash('Ошибка отправки кода. Проверьте настройки почты.', 'danger')


def send_password_reset_email(user):
    serializer = URLSafeTimedSerializer(current_app.secret_key)
    token = serializer.dumps(user.email, salt='password-reset-salt')
    reset_url = url_for('auth.reset_password', token=token, _external=True)

    sender = os.getenv("MAIL_EMAIL")
    password = os.getenv("MAIL_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = user.email
    msg["Subject"] = "Сброс пароля — Ваш интернет-магазин"

    body = f"""
Здравствуйте!

Вы запросили сброс пароля для аккаунта {user.email}.

Перейдите по ссылке, чтобы установить новый пароль:
{reset_url}

Ссылка действительна 1 час.

Если вы не запрашивали сброс — просто проигнорируйте письмо.
"""
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, password)
        server.sendmail(sender, user.email, msg.as_string())
        server.quit()
        print(f"✅ Письмо для сброса пароля успешно отправлено на {user.email}")
    except Exception as e:
        print(f"❌ SMTP ошибка при сбросе пароля: {e}")
        # Для разработки можно раскомментировать:
        # flash('Ошибка отправки письма. Проверьте консоль.', 'danger')

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ====================== ТВОИ СТАРЫЕ РОУТЫ ======================

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))  # или 'index' — как у тебя

    form = RegistrationForm()

    if form.validate_on_submit():
        try:
            code = str(random.randint(100000, 999999))
            send_email_code(form.email.data, code)

            session['temp_user_email'] = form.email.data
            session['temp_user_password'] = form.password.data
            session['temp_user_code'] = code
            session['temp_user_expiry'] = (datetime.utcnow() + timedelta(minutes=10)).timestamp()

            flash('Код подтверждения отправлен на email!', 'success')
            return redirect(url_for('auth.verify_registration_code'))

        except Exception as e:
            print("Ошибка отправки email:", e)
            flash('Ошибка отправки кода. Попробуйте позже.', 'danger')

    return render_template('auth/register.html', form=form)


@auth_bp.route('/verify-registration-code', methods=['GET', 'POST'])
def verify_registration_code():
    if 'temp_user_email' not in session:
        flash('Сначала зарегистрируйтесь', 'warning')
        return redirect(url_for('auth.register'))

    if request.method == 'POST':
        entered_code = request.form.get('code')
        stored_code = session.get('temp_user_code')
        expiry = session.get('temp_user_expiry')

        if stored_code == entered_code and expiry and datetime.fromtimestamp(expiry) > datetime.utcnow():
            try:
                hashed_password = bcrypt.generate_password_hash(session['temp_user_password']).decode('utf-8')

                user = User(
                    email=session['temp_user_email'],
                    password_hash=hashed_password,
                    role=UserRole.buyer,
                    preferences={}
                )

                db.session.add(user)
                db.session.flush()

                log = AuditLog(
                    user_id=user.id,
                    action='register',
                    ip_address=request.remote_addr,
                    details={'email': user.email, 'method': 'email_verification'}
                )
                db.session.add(log)
                db.session.commit()

                # Очищаем сессию
                session.pop('temp_user_email', None)
                session.pop('temp_user_password', None)
                session.pop('temp_user_code', None)
                session.pop('temp_user_expiry', None)

                flash('Регистрация успешна! Теперь войдите.', 'success')
                return redirect(url_for('auth.login'))

            except Exception as e:
                db.session.rollback()
                print("Ошибка сохранения пользователя:", e)
                flash('Ошибка при регистрации. Попробуйте позже.', 'danger')
                return redirect(url_for('auth.register'))
        else:
            if not expiry or datetime.fromtimestamp(expiry) <= datetime.utcnow():
                flash('Код истёк. Зарегистрируйтесь заново.', 'danger')
                session.pop('temp_user_email', None)
                session.pop('temp_user_password', None)
                session.pop('temp_user_code', None)
                session.pop('temp_user_expiry', None)
                return redirect(url_for('auth.register'))
            else:
                flash('Неверный код подтверждения', 'danger')

    return render_template('auth/verify_registration_code.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role.name == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('main.index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            if user.locked_until and user.locked_until > datetime.utcnow():
                flash('Аккаунт заблокирован на 10 минут после 5 неудачных попыток.', 'danger')
                return render_template('auth/login.html', form=form)

            user.failed_login_attempts = 0
            db.session.commit()

            login_user(user, remember=True)

            log = AuditLog(
                user_id=user.id,
                action='login_success',
                ip_address=request.remote_addr,
                details={'method': 'password_only (dev mode)'}
            )
            db.session.add(log)
            db.session.commit()

            flash('Вход выполнен успешно (2FA временно отключена)', 'success')

            if user.role.name == 'admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('main.index'))

        else:
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=10)
                    flash('Слишком много попыток. Аккаунт заблокирован на 10 минут.', 'danger')
                    log = AuditLog(user_id=user.id, action='account_locked', ip_address=request.remote_addr, details={'attempts': user.failed_login_attempts})
                else:
                    log = AuditLog(user_id=user.id, action='login_failed', ip_address=request.remote_addr, details={'attempts': user.failed_login_attempts})
                db.session.add(log)
                db.session.commit()
            else:
                flash('Неверный email или пароль', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    log = AuditLog(
        user_id=current_user.id,
        action='logout',
        ip_address=request.remote_addr,
        details={}
    )
    db.session.add(log)
    db.session.commit()

    logout_user()
    flash('Вы вышли из аккаунта', 'info')
    return redirect(url_for('main.index'))   # или url_for('index')


# ====================== НОВЫЕ РОУТЫ ДЛЯ СБРОСА ПАРОЛЯ ======================

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        flash('Вы уже авторизованы', 'info')
        return redirect(url_for('main.index'))

    form = ResetPasswordRequestForm()

    if form.validate_on_submit():
        email_input = form.email.data.strip()
        email_lower = email_input.lower()

        print("=== ЗАПРОС СБРОСА ПАРОЛЯ ===")
        print(f"Email из формы: '{email_input}'")
        print(f"Для поиска в БД используем lower: '{email_lower}'")

        # ←←← КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: case-insensitive поиск
        from sqlalchemy import func
        user = User.query.filter(func.lower(User.email) == email_lower).first()

        print(f"Пользователь найден в БД: {user is not None}")
        if user:
            print(f"→ Найден пользователь: {user.email} (id={user.id})")
            print("→ Запускаем отправку письма...")
            send_password_reset_email(user)
            print("→ Функция send_password_reset_email вызвана (смотри строки выше/ниже)")

            # Аудит
            audit = AuditLog(
                user_id=user.id,
                action='password_reset_requested',
                ip_address=request.remote_addr,
                details={'method': 'email', 'email_used': email_input}
            )
            db.session.add(audit)
            db.session.commit()
        else:
            print("→ Email НЕ найден даже после lower()")

        flash('Если email зарегистрирован, на него отправлена ссылка для сброса пароля', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        serializer = URLSafeTimedSerializer(current_app.secret_key)
        email = serializer.loads(token, salt='password-reset-salt', max_age=3600)
    except (SignatureExpired, BadSignature):
        flash('Ссылка для сброса пароля недействительна или истекла', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.filter_by(email=email).first_or_404()
    form = ResetPasswordForm()

    if form.validate_on_submit():
        user.password_hash = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        db.session.commit()

        audit = AuditLog(
            user_id=user.id,
            action='password_reset_success',
            ip_address=request.remote_addr,
            details={'method': 'email_token'}
        )
        db.session.add(audit)
        db.session.commit()

        flash('Пароль успешно изменён! Теперь вы можете войти.', 'success')
        logout_user()
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', form=form)


# ====================== CSRF ======================
# Эти строки должны быть в самом конце файла, после всех def
csrf.exempt(register)
csrf.exempt(verify_registration_code)