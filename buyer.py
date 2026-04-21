from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user, logout_user
from app.decorators import buyer_required
from app import db, bcrypt, csrf
from app.models import (
    Product, CartItem, Favorite, Order, OrderItem, OrderStatus,
    AuditLog, Category
)
from app.forms import ProfileForm, CheckoutForm, ChangePasswordForm
from cryptography.fernet import Fernet
import os
from datetime import datetime

buyer_bp = Blueprint('buyer', __name__, url_prefix='/buyer')


@buyer_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@buyer_required
def profile():
    # ←←← КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: используем prefix, чтобы формы не конфликтовали
    profile_form = ProfileForm(prefix='profile_')
    password_form = ChangePasswordForm(prefix='password_')

    key = os.environ.get('ENCRYPTION_KEY').encode()
    cipher = Fernet(key)

    # Расшифровка для отображения
    decrypted_phone = None
    decrypted_address = None
    if current_user.phone_encrypted:
        try:
            decrypted_phone = cipher.decrypt(current_user.phone_encrypted.encode()).decode()
        except Exception:
            decrypted_phone = "[Ошибка расшифровки]"

    if current_user.address_encrypted:
        try:
            decrypted_address = cipher.decrypt(current_user.address_encrypted.encode()).decode()
        except Exception:
            decrypted_address = "[Ошибка расшифровки]"

    changed_fields = []

    # ==================== 1. Редактирование профиля ====================
    if request.method == 'POST' and profile_form.submit.data and profile_form.validate_on_submit():
        if profile_form.first_name.data != current_user.first_name:
            current_user.first_name = profile_form.first_name.data
            changed_fields.append('first_name')
        if profile_form.last_name.data != current_user.last_name:
            current_user.last_name = profile_form.last_name.data
            changed_fields.append('last_name')

        # Телефон
        if profile_form.phone.data:
            new_enc = cipher.encrypt(profile_form.phone.data.encode()).decode()
            if new_enc != current_user.phone_encrypted:
                current_user.phone_encrypted = new_enc
                changed_fields.append('phone')
        elif current_user.phone_encrypted:
            current_user.phone_encrypted = None
            changed_fields.append('phone_removed')

        # Адрес
        if profile_form.address.data:
            new_enc = cipher.encrypt(profile_form.address.data.encode()).decode()
            if new_enc != current_user.address_encrypted:
                current_user.address_encrypted = new_enc
                changed_fields.append('address')
        elif current_user.address_encrypted:
            current_user.address_encrypted = None
            changed_fields.append('address_removed')

        db.session.commit()

        if changed_fields:
            audit = AuditLog(
                user_id=current_user.id,
                action='update_profile',
                ip_address=request.remote_addr,
                details={'changed_fields': changed_fields}
            )
            db.session.add(audit)
            db.session.commit()

        flash('Профиль успешно обновлён', 'success')
        return redirect(url_for('buyer.profile'))

    # ==================== 2. Смена пароля ====================
    if request.method == 'POST' and password_form.submit.data and password_form.validate_on_submit():
        # Проверяем старый пароль
        if not bcrypt.check_password_hash(current_user.password_hash, password_form.old_password.data):
            flash('Текущий пароль указан неверно', 'danger')
            return redirect(url_for('buyer.profile'))

        # Меняем пароль
        current_user.password_hash = bcrypt.generate_password_hash(
            password_form.new_password.data
        ).decode('utf-8')

        db.session.commit()

        # Аудит
        audit = AuditLog(
            user_id=current_user.id,
            action='change_password',
            ip_address=request.remote_addr,
            details={'method': 'profile'}
        )
        db.session.add(audit)
        db.session.commit()

        flash('Пароль успешно изменён. Пожалуйста, войдите заново.', 'success')
        logout_user()
        return redirect(url_for('auth.login'))

    # Заполняем форму профиля текущими данными
    profile_form.first_name.data = current_user.first_name
    profile_form.last_name.data = current_user.last_name
    profile_form.phone.data = decrypted_phone
    profile_form.address.data = decrypted_address

    return render_template(
        'buyer/profile.html',
        profile_form=profile_form,
        password_form=password_form,
        decrypted_phone=decrypted_phone,
        decrypted_address=decrypted_address
    )
    

@buyer_bp.route('/cart')
@login_required
@buyer_required
def cart():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in cart_items)
    return render_template('buyer/cart.html', cart_items=cart_items, total=total)

@buyer_bp.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
@buyer_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    quantity = int(request.form.get('quantity', 1))
    
    cart_item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if cart_item:
        cart_item.quantity += quantity
    else:
        cart_item = CartItem(user_id=current_user.id, product_id=product_id, quantity=quantity)
        db.session.add(cart_item)
    
    db.session.commit()
    
    # Аудит
    audit = AuditLog(
        user_id=current_user.id,
        action='add_to_cart',
        ip_address=request.remote_addr,
        details={
            'product_id': product_id,
            'product_name': product.name,
            'quantity_added': quantity
        }
    )
    db.session.add(audit)
    db.session.commit()
    
    flash(f'{product.name} добавлен в корзину', 'success')
    return redirect(request.referrer or url_for('main.index') + '#catalog')

@buyer_bp.route('/cart/remove/<int:item_id>', methods=['POST'])
@login_required
@buyer_required
def remove_from_cart(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id != current_user.id:
        flash('Товар не найден в вашей корзине', 'danger')
        return redirect(url_for('buyer.cart'))
    
    product_name = item.product.name
    db.session.delete(item)
    db.session.commit()
    
    # Аудит
    audit = AuditLog(
        user_id=current_user.id,
        action='remove_from_cart',
        ip_address=request.remote_addr,
        details={
            'product_id': item.product_id,
            'product_name': product_name,
            'quantity_removed': item.quantity
        }
    )
    db.session.add(audit)
    db.session.commit()
    
    flash('Товар удалён из корзины', 'info')
    return redirect(url_for('buyer.cart'))

@buyer_bp.route('/favorites')
@login_required
@buyer_required
def favorites():
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    return render_template('buyer/favorites.html', favorites=favorites)

@buyer_bp.route('/favorites/add/<int:product_id>', methods=['POST'])
@login_required
@buyer_required
def add_to_favorites(product_id):
    product = Product.query.get_or_404(product_id)
    
    existing = Favorite.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash(f'{product.name} удалён из избранного', 'info')
    else:
        fav = Favorite(user_id=current_user.id, product_id=product_id)
        db.session.add(fav)
        db.session.commit()
        flash(f'{product.name} добавлен в избранное', 'success')
    
    return redirect(request.referrer or url_for('main.index') + '#catalog')


@buyer_bp.route('/favorites/remove/<int:product_id>', methods=['POST'])
@login_required
@buyer_required
def remove_from_favorites(product_id):
    fav = Favorite.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    
    if fav:
        product_name = fav.product.name if fav.product else "Товар"
        db.session.delete(fav)
        db.session.commit()
        flash(f'{product_name} удалён из избранного', 'info')
    else:
        flash('Товар не найден в избранном', 'warning')
    
    return redirect(request.referrer or url_for('buyer.favorites') + '#catalog')

@buyer_bp.route('/cart/remove_by_product/<int:product_id>', methods=['POST'])
@login_required
@buyer_required
def remove_from_cart_by_product(product_id):
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('Товар удалён из корзины', 'info')
    return redirect(request.referrer or url_for('main.index'))

@buyer_bp.route('/cart/update_quantity/<int:product_id>', methods=['POST'])
@login_required
@buyer_required
def update_cart_quantity(product_id):
    quantity = int(request.form.get('quantity', 1))
    if quantity < 0:
        quantity = 0  # при 0 удаляем
    
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if not item:
        flash('Товар не найден в корзине', 'danger')
        return redirect(request.referrer or url_for('buyer.cart'))
    
    old_qty = item.quantity
    
    if quantity == 0:
        product_name = item.product.name
        db.session.delete(item)
        action = 'remove_from_cart'
        details = {'product_id': product_id, 'product_name': product_name, 'quantity_removed': old_qty}
    else:
        item.quantity = quantity
        db.session.add(item)
        action = 'update_cart_quantity'
        details = {
            'product_id': product_id,
            'product_name': item.product.name,
            'old_quantity': old_qty,
            'new_quantity': quantity
        }
    
    db.session.commit()
    
    # Аудит
    audit = AuditLog(
        user_id=current_user.id,
        action=action,
        ip_address=request.remote_addr,
        details=details
    )
    db.session.add(audit)
    db.session.commit()
    
    flash(f'Количество обновлено', 'success')
    return redirect(request.referrer or url_for('buyer.cart'))

@buyer_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
@buyer_required
def checkout():
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash('Ваша корзина пуста', 'warning')
        return redirect(url_for('buyer.cart'))

    total = sum(item.product.price * item.quantity for item in cart_items)

    form = CheckoutForm()

    key = os.environ.get('ENCRYPTION_KEY').encode()
    cipher = Fernet(key)

    if form.validate_on_submit():
        # Шифруем адрес
        encrypted_address = cipher.encrypt(form.address.data.encode()).decode()

        # Создаём заказ
        order = Order(
            user_id=current_user.id,
            status=OrderStatus.pending,
            address_encrypted=encrypted_address,
            total_price=total
        )
        db.session.add(order)
        db.session.flush()  # получаем order.id до commit

        # Переносим товары из корзины в заказ
        for item in cart_items:
            order_item = OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                quantity=item.quantity,
                price_at_purchase=item.product.price
            )
            db.session.add(order_item)

            # Опционально: уменьшить остаток на складе (раскомментировать, если нужно)
            # item.product.quantity_available -= item.quantity
            # db.session.add(item.product)

        # Очищаем корзину
        for item in cart_items:
            db.session.delete(item)

        # Аудит создания заказа
        audit = AuditLog(
            user_id=current_user.id,
            action='create_order',
            ip_address=request.remote_addr,
            details={
                'order_id': order.id,
                'total': total,
                'item_count': len(cart_items),
                'payment_method': form.payment_method.data
            }
        )
        db.session.add(audit)

        db.session.commit()

        flash(f'Заказ #{order.id} успешно оформлен!', 'success')
        return redirect(url_for('buyer.order_success', order_id=order.id))

    return render_template('buyer/checkout.html', form=form, cart_items=cart_items, total=total)

@buyer_bp.route('/order/<int:order_id>')
@login_required
@buyer_required
def order_detail(order_id):
    # Находим заказ, принадлежащий только текущему пользователю
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()

    # Расшифровка адреса
    decrypted_address = None
    key = os.environ.get('ENCRYPTION_KEY').encode()
    cipher = Fernet(key)
    
    if order.address_encrypted:
        try:
            decrypted_address = cipher.decrypt(order.address_encrypted.encode()).decode()
        except Exception as e:
            decrypted_address = f"[Ошибка расшифровки: {str(e)}]"

    # Получаем все позиции заказа
    order_items = OrderItem.query.filter_by(order_id=order.id).all()

    return render_template(
        'buyer/order_detail.html',
        order=order,
        decrypted_address=decrypted_address,
        order_items=order_items
    )
    
@buyer_bp.route('/order/<int:order_id>/cancel', methods=['POST'])
@login_required
@buyer_required
def cancel_order(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    
    if order.status not in [OrderStatus.pending, OrderStatus.processing]:
        flash('Заказ нельзя отменить на текущем статусе', 'danger')
        return redirect(url_for('buyer.order_detail', order_id=order_id))
    
    order.status = OrderStatus.cancelled
    db.session.commit()
    
    # Аудит
    audit = AuditLog(
        user_id=current_user.id,
        action='cancel_order',
        ip_address=request.remote_addr,
        details={'order_id': order.id}
    )
    db.session.add(audit)
    db.session.commit()
    
    flash('Заказ успешно отменён', 'success')
    return redirect(url_for('buyer.order_detail', order_id=order_id))

@buyer_bp.route('/orders')
@login_required
@buyer_required
def orders():
    # Получаем все заказы пользователя, сортируем по дате (новые сверху)
    orders = Order.query.filter_by(user_id=current_user.id)\
                        .order_by(Order.created_at.desc())\
                        .all()

    # Для каждого заказа получаем расшифрованный адрес (если нужно показывать в списке)
    # Но в списке можно не показывать адрес, только на детальной странице
    key = os.environ.get('ENCRYPTION_KEY').encode()
    cipher = Fernet(key)

    decrypted_addresses = {}
    for order in orders:
        if order.address_encrypted:
            try:
                decrypted_addresses[order.id] = cipher.decrypt(order.address_encrypted.encode()).decode()
            except:
                decrypted_addresses[order.id] = "[ошибка расшифровки]"

    return render_template(
        'buyer/orders.html',
        orders=orders,
        decrypted_addresses=decrypted_addresses
    )
    
@buyer_bp.route('/order/<int:order_id>/success')
@login_required
@buyer_required
def order_success(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()

    # Расшифровка адреса для отображения
    decrypted_address = None
    if order.address_encrypted:
        try:
            key = os.environ.get('ENCRYPTION_KEY').encode()
            cipher = Fernet(key)
            decrypted_address = cipher.decrypt(order.address_encrypted.encode()).decode()
        except Exception as e:
            decrypted_address = f"[Ошибка расшифровки: {str(e)}]"

    return render_template(
        'buyer/order_success.html',
        order=order,
        decrypted_address=decrypted_address
    )
    
@buyer_bp.route('/order/<int:order_id>/simulate_payment', methods=['POST'])
@login_required
@buyer_required
def simulate_payment(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Проверка, что заказ принадлежит текущему пользователю
    if order.user_id != current_user.id:
        abort(403)
    
    # Проверка, что заказ ещё не оплачен
    if order.status == OrderStatus.paid:
        flash('Заказ уже оплачен.', 'info')
        return redirect(url_for('buyer.order_detail', order_id=order_id))
    
    # Симулируем оплату
    order.status = OrderStatus.paid
    # order.updated_at = func.now()  # если нужно
    db.session.commit()
    
    # Можно добавить аудит
    # log_audit_action(current_user.id, 'simulate_payment', {'order_id': order_id})
    
    flash('Оплата успешно симулирована! Статус заказа изменён на "paid".', 'success')
    return redirect(url_for('buyer.order_success', order_id=order_id))  # или order_detail

csrf.exempt(add_to_cart)
csrf.exempt(remove_from_cart)
csrf.exempt(add_to_favorites)
csrf.exempt(remove_from_favorites)
csrf.exempt(remove_from_cart_by_product)
csrf.exempt(update_cart_quantity)
csrf.exempt(simulate_payment)
csrf.exempt(cancel_order)