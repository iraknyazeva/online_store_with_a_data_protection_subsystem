from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user, login_required
from app.models import UserRole

def buyer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Пожалуйста, войдите в аккаунт.', 'info')
            return redirect(url_for('auth.login'))
        
        if current_user.role != UserRole.buyer:
            flash('Доступ только для покупателей.', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Пожалуйста, войдите в аккаунт.', 'info')
            return redirect(url_for('auth.login'))
        
        if current_user.role != UserRole.admin:
            flash('Доступ только для администраторов.', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function
