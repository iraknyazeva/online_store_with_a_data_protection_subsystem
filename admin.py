from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required
from app.decorators import admin_required
from app import db
from app.models import Product, Category, ProductCategory
from app.forms import ProductForm  # создадим ниже
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import cv2  # OpenCV
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from app.models import (
    Product, CartItem, Favorite, Order, User, OrderItem, OrderStatus, AuditLog, Category
)  
from flask_login import current_user
from flask import request
from sqlalchemy import desc
from cryptography.fernet import Fernet
from app.models import UserRole
from app.utils.image_features import extract_image_features
import json
from app import csrf

admin_bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='templates/admin')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@admin_bp.route('/products')
@login_required
@admin_required
def products_list():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    category_id = request.args.get('category', type=int)

    query = Product.query

    if search:
        query = query.filter(
            (Product.name.ilike(f'%{search}%')) | (Product.description.ilike(f'%{search}%'))
        )

    if category_id:
        query = query.join(Product.categories).filter(Category.id == category_id)

    products = query.paginate(page=page, per_page=20)

    categories = Category.query.all()

    return render_template(
        'admin/products_list.html',
        products=products,
        categories=categories,
        search=search,
        selected_category=category_id
    )

@admin_bp.route('/product/add', methods=['GET', 'POST'])
@admin_required
def product_add():
    form = ProductForm()
    categories = Category.query.filter_by(parent_id=None).order_by(Category.name).all()

    if form.validate_on_submit():
        new_product = Product(
            name=form.name.data.strip(),
            description=form.description.data.strip() or None,
            price=form.price.data,
            quantity_available=form.quantity_available.data
        )

        # Категории
        selected_ids = form.categories.data or []
        if selected_ids:
            new_product.categories = Category.query.filter(Category.id.in_(selected_ids)).all()

        # Фото
        if form.image.data and allowed_file(form.image.data.filename):
            filename = secure_filename(form.image.data.filename)
            upload_path = os.path.join(current_app.root_path, 'static/uploads', filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            form.image.data.save(upload_path)
            new_product.image_path = f'/static/uploads/{filename}'

        db.session.add(new_product)
        db.session.commit()

        # === Автоматическое заполнение image_features ===
        if new_product.image_path:
            update_image_features(new_product, new_product.image_path)
            db.session.commit()

        # Аудит
        audit = AuditLog(
            user_id=current_user.id,
            action='add_product',
            ip_address=request.remote_addr,
            details={
                'product_id': new_product.id,
                'name': new_product.name,
                'price': new_product.price
            }
        )
        db.session.add(audit)
        db.session.commit()

        flash(f'Товар "{new_product.name}" успешно добавлен', 'success')
        return redirect(url_for('admin.products_list'))

    return render_template('admin/add_product.html', form=form, categories=categories)

@admin_bp.route('/product/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    form = ProductForm(obj=product)
    form.categories.choices = [(c.id, c.name) for c in Category.query.all()]
    form.categories.data = [c.id for c in product.categories]

    if form.validate_on_submit():
        product.name = form.name.data
        product.description = form.description.data
        product.price = form.price.data
        product.quantity_available = form.quantity_available.data

        # Категории
        selected_categories = Category.query.filter(Category.id.in_(form.categories.data)).all()
        product.categories = selected_categories

        # Фото (обновление, если загружено новое)
        if form.image.data and allowed_file(form.image.data.filename):
            filename = secure_filename(form.image.data.filename)
            upload_path = os.path.join(current_app.root_path, 'static/uploads', filename)
            form.image.data.save(upload_path)
            product.image_path = f'/static/uploads/{filename}'

            # Пересчитываем признаки
            img = cv2.imread(upload_path, cv2.IMREAD_GRAYSCALE)
            orb = cv2.ORB_create()
            keypoints, descriptors = orb.detectAndCompute(img, None)
            if descriptors is not None:
                product.image_features = descriptors.tolist()

        db.session.commit()

        # Аудит
        audit = AuditLog(
            user_id=current_user.id,
            action='edit_product',
            ip_address=request.remote_addr,
            details={'product_id': product.id, 'name': product.name}
        )
        db.session.add(audit)
        db.session.commit()

        flash(f'Товар "{product.name}" обновлён', 'success')
        return redirect(url_for('admin.products_list'))

    return render_template('admin/product_form.html', form=form, title='Редактировать товар', product=product)

@admin_bp.route('/product/delete/<int:product_id>', methods=['POST'])
@admin_required
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)

    audit = AuditLog(
        user_id=current_user.id,
        action='delete_product',
        ip_address=request.remote_addr,
        details={'product_id': product.id, 'name': product.name}
    )
    db.session.add(audit)

    db.session.delete(product)
    db.session.commit()

    flash(f'Товар "{product.name}" удалён', 'success')
    return redirect(url_for('admin.products_list'))

@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Статистика для дашборда
    total_users = User.query.count()
    total_products = Product.query.count()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status=OrderStatus.pending).count()
    revenue = db.session.query(db.func.sum(Order.total_price)).scalar() or 0

    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        total_products=total_products,
        total_orders=total_orders,
        pending_orders=pending_orders,
        revenue=revenue,
        recent_orders=recent_orders,
        recent_users=recent_users
    )

@admin_bp.route('/orders')
@login_required
@admin_required
def orders_list():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', None)

    query = Order.query.order_by(desc(Order.created_at))

    if status_filter and status_filter != 'all':
        try:
            status_enum = OrderStatus[status_filter]
            query = query.filter(Order.status == status_enum)
        except KeyError:
            pass  # если некорректный статус — игнорируем

    orders = query.paginate(page=page, per_page=20)

    # Для отображения расшифрованных адресов (опционально, можно убрать если не нужно)
    decrypted_addresses = {}
    key = os.environ.get('ENCRYPTION_KEY').encode()
    cipher = Fernet(key)

    for order in orders.items:
        if order.address_encrypted:
            try:
                decrypted_addresses[order.id] = cipher.decrypt(
                    order.address_encrypted.encode()
                ).decode()
            except:
                decrypted_addresses[order.id] = "[ошибка расшифровки]"

    return render_template(
        'admin/orders_list.html',
        orders=orders,
        status_filter=status_filter,
        decrypted_addresses=decrypted_addresses
    )


@admin_bp.route('/order/<int:order_id>/update_status', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status_str = request.form.get('status')

    if not new_status_str:
        flash('Статус не выбран', 'danger')
        return redirect(url_for('admin.orders_list'))

    try:
        new_status = OrderStatus[new_status_str]
    except KeyError:
        flash('Неверный статус', 'danger')
        return redirect(url_for('admin.orders_list'))

    if order.status == new_status:
        flash('Статус уже установлен', 'info')
        return redirect(url_for('admin.orders_list'))

    old_status = order.status.value
    order.status = new_status
    db.session.commit()

    # Аудит
    audit = AuditLog(
        user_id=current_user.id,
        action='update_order_status',
        ip_address=request.remote_addr,
        details={
            'order_id': order.id,
            'old_status': old_status,
            'new_status': new_status.value,
            'user_email': order.user.email if order.user else 'удалён'
        }
    )
    db.session.add(audit)
    db.session.commit()

    flash(f'Статус заказа #{order.id} изменён на "{new_status.value}"', 'success')
    return redirect(url_for('admin.orders_list'))

from sqlalchemy import desc

@admin_bp.route('/audit-logs')
@login_required
@admin_required
def audit_logs():
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action', None)
    user_id_filter = request.args.get('user_id', type=int)
    date_from = request.args.get('date_from')   # формат YYYY-MM-DD
    date_to = request.args.get('date_to')

    query = AuditLog.query.order_by(desc(AuditLog.timestamp))

    # Фильтр по действию
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)

    # Фильтр по пользователю
    if user_id_filter:
        query = query.filter(AuditLog.user_id == user_id_filter)

    # Фильтр по дате (если указаны)
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(AuditLog.timestamp >= from_date)
        except ValueError:
            flash('Неверный формат даты "от" (ожидается YYYY-MM-DD)', 'warning')

    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            # до конца дня
            to_date = to_date.replace(hour=23, minute=59, second=59)
            query = query.filter(AuditLog.timestamp <= to_date)
        except ValueError:
            flash('Неверный формат даты "до" (ожидается YYYY-MM-DD)', 'warning')

    logs = query.paginate(page=page, per_page=25)

    # Для удобства: список уникальных действий (для выпадающего списка)
    actions = db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
    actions = [a[0] for a in actions if a[0]]

    # Список пользователей (для фильтра)
    users = User.query.with_entities(User.id, User.email).order_by(User.email).all()

    return render_template(
        'admin/audit_logs.html',
        logs=logs,
        actions=actions,
        users=users,
        action_filter=action_filter,
        user_id_filter=user_id_filter,
        date_from=date_from,
        date_to=date_to
    )
    
@admin_bp.route('/users')
@login_required
@admin_required
def users_list():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', None)
    active_filter = request.args.get('active', None)  # 'active', 'blocked', None = все

    query = User.query.order_by(User.created_at.desc())

    if search:
        query = query.filter(
            db.or_(
                User.email.ilike(f'%{search}%'),
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%')
            )
        )

    if role_filter in ['buyer', 'admin']:
        query = query.filter(User.role == UserRole[role_filter])

    if active_filter == 'active':
        query = query.filter(User.account_active == True)
    elif active_filter == 'blocked':
        query = query.filter(User.account_active == False)

    users = query.paginate(page=page, per_page=20)

    return render_template(
        'admin/users_list.html',
        users=users,
        search=search,
        role_filter=role_filter,
        active_filter=active_filter
    )


@admin_bp.route('/user/<int:user_id>/toggle_active', methods=['POST'])
@login_required
@admin_required
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)

    if user.role == UserRole.admin and current_user.id != user.id:
        flash('Нельзя блокировать другого администратора', 'danger')
        return redirect(url_for('admin.users_list'))

    old_status = user.account_active
    user.account_active = not user.account_active
    db.session.commit()

    action = 'block_user' if not user.account_active else 'unblock_user'

    audit = AuditLog(
        user_id=current_user.id,
        action=action,
        ip_address=request.remote_addr,
        details={
            'target_user_id': user.id,
            'target_email': user.email,
            'old_status': old_status,
            'new_status': user.account_active
        }
    )
    db.session.add(audit)
    db.session.commit()

    status_text = 'заблокирован' if not user.account_active else 'разблокирован'
    flash(f'Пользователь {user.email} {status_text}', 'success')
    return redirect(url_for('admin.users_list'))

def update_image_features(product, image_path):
    """Обновляет image_features для товара"""
    if not image_path:
        return
    
    # Полный путь к файлу
    if image_path.startswith('/static/'):
        full_path = image_path.lstrip('/')
    else:
        full_path = os.path.join(current_app.root_path, image_path.lstrip('/'))
    
    features = extract_image_features(full_path)
    if features:
        product.image_features = json.dumps(features)
        print(f"✓ image_features обновлены для товара #{product.id}")
    else:
        print(f"✗ Не удалось извлечь признаки для товара #{product.id}")
        
csrf.exempt(product_delete)