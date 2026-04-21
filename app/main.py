from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy import func, or_
from datetime import datetime, timedelta
from . import db
from .models import Product, Category, Favorite, OrderItem, CartItem, SearchHistory, Order, Review, ProductCategory
from .forms import ReviewForm
import json
from math import sqrt

main_bp = Blueprint('main', __name__)


def get_personalized_products(user, days=60):
    """Улучшенная версия рекомендаций: баланс между персонализацией и разнообразием"""
    if not user or not user.is_authenticated:
        return Product.query.order_by(Product.created_at.desc()).all()

    cutoff_date = datetime.utcnow() - timedelta(days=days)
    score_dict = {}                    # product_id -> score
    user_category_weights = {}         # category_id -> вес категории пользователя

    # ====================== 1. Сбор взаимодействий пользователя ======================
    # Покупки (самый сильный сигнал)
    for item in OrderItem.query.join(OrderItem.order).filter(
        Order.user_id == user.id,
        Order.created_at >= cutoff_date
    ).all():
        days_ago = (datetime.utcnow() - item.order.created_at).days
        recency = 1 / (1 + days_ago / 7)
        score_dict[item.product_id] = score_dict.get(item.product_id, 0) + 12 * recency

        for cat in item.product.categories:
            user_category_weights[cat.id] = user_category_weights.get(cat.id, 0) + 8 * recency

    # Избранное
    for fav in Favorite.query.filter(
        Favorite.user_id == user.id,
        Favorite.created_at >= cutoff_date
    ).all():
        days_ago = (datetime.utcnow() - fav.created_at).days
        recency = 1 / (1 + days_ago / 7)
        score_dict[fav.product_id] = score_dict.get(fav.product_id, 0) + 7 * recency

        for cat in fav.product.categories:
            user_category_weights[cat.id] = user_category_weights.get(cat.id, 0) + 5 * recency

    # Корзина
    for item in CartItem.query.filter(
        CartItem.user_id == user.id,
        CartItem.created_at >= cutoff_date
    ).all():
        days_ago = (datetime.utcnow() - item.created_at).days
        recency = 1 / (1 + days_ago / 7)
        score_dict[item.product_id] = score_dict.get(item.product_id, 0) + 4 * recency

        for cat in item.product.categories:
            user_category_weights[cat.id] = user_category_weights.get(cat.id, 0) + 3 * recency

    # ====================== 2. Поиск похожих товаров ======================
    def get_similar_products(seed_product, limit=15):
        if not seed_product.image_features:
            return []
        try:
            target_features = json.loads(seed_product.image_features) if isinstance(seed_product.image_features, str) else seed_product.image_features
            target_cats = {cat.id for cat in seed_product.categories}

            candidates = Product.query.filter(
                Product.id != seed_product.id,
                Product.image_features.isnot(None)
            ).limit(60).all()

            similarities = []
            for p in candidates:
                if not p.image_features:
                    continue
                p_features = json.loads(p.image_features) if isinstance(p.image_features, str) else p.image_features
                visual_sim = cosine_similarity(target_features, p_features)

                p_cats = {cat.id for cat in p.categories}
                cat_overlap = len(target_cats & p_cats) * 0.4

                score = visual_sim * 0.75 + cat_overlap
                similarities.append((p, score))

            similarities.sort(key=lambda x: x[1], reverse=True)
            return [item[0] for item in similarities[:limit]]
        except:
            return []

    # Применяем похожие товары
    for product_id, base_score in list(score_dict.items()):
        product = Product.query.get(product_id)
        if not product:
            continue
        similar_list = get_similar_products(product)
        for similar in similar_list:
            score_dict[similar.id] = score_dict.get(similar.id, 0) + base_score * 0.65

    # ====================== 3. Финальный score ======================
    all_products = Product.query.all()
    for p in all_products:
        base = score_dict.get(p.id, 0)

        # Лёгкий бонус за любимые категории
        cat_bonus = 0
        for cat in p.categories:
            cat_bonus += user_category_weights.get(cat.id, 0) * 0.35
        final_score = base + cat_bonus

        p.personal_score = final_score

    # Сортируем по score
    all_products.sort(key=lambda p: p.personal_score, reverse=True)

    # ====================== 4. Добавляем разнообразие ======================
    if len(all_products) > 15:
        final_list = []
        seen_categories = set()
        
        for p in all_products[:30]:   # берём из топ-30
            primary_cat = p.categories[0].id if p.categories else 0
            if primary_cat not in seen_categories or len(final_list) < 10:
                final_list.append(p)
                seen_categories.add(primary_cat)
            if len(final_list) >= 24:   # показываем до 24 товаров
                break

        # Добавляем остаток
        for p in all_products:
            if p not in final_list:
                final_list.append(p)
            if len(final_list) >= 30:
                break
        return final_list

    return all_products


@main_bp.route('/')
def index():
    search = request.args.get('search', '').strip()
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')
    selected_categories = request.args.getlist('category')

    if current_user.is_authenticated and not search and not min_price and not max_price and not selected_categories:
        products = get_personalized_products(current_user, days=60)
    else:
        query = Product.query

        if search:
            query = query.filter(
                or_(
                    Product.name.ilike(f'%{search}%'),
                    Product.description.ilike(f'%{search}%')
                )
            )

        if min_price:
            try:
                query = query.filter(Product.price >= float(min_price))
            except ValueError:
                pass
        if max_price:
            try:
                query = query.filter(Product.price <= float(max_price))
            except ValueError:
                pass

        if selected_categories:
            try:
                cat_ids = [int(cid) for cid in selected_categories if cid.strip()]
                if cat_ids:
                    query = query.filter(
                        Product.categories.any(Category.id.in_(cat_ids))
                    )
            except ValueError:
                pass

        products = query.all()

    # Логируем поиск
    if search and current_user.is_authenticated:
        db.session.add(SearchHistory(user_id=current_user.id, query=search))
        db.session.commit()

    categories = Category.query.all()

    in_cart = [item.product_id for item in getattr(current_user, 'cart_items', [])]
    in_favorites = [p.id for p in getattr(current_user, 'favorites', [])]

    return render_template('main/index.html',
                           products=products,
                           categories=categories,
                           in_cart=in_cart,
                           in_favorites=in_favorites)

@main_bp.route('/search')
def search():
    """Поиск товаров (редирект на главную с параметром search)"""
    query = request.args.get('q', '')
    return redirect(url_for('main/index.html', search=query))

@main_bp.route('/product/<int:product_id>', methods=['GET', 'POST'])
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)

    form = ReviewForm()

    # --- Обработка отправки отзыва ---
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash('Для оставления отзыва необходимо войти в аккаунт.', 'warning')
            return redirect(url_for('auth.login', next=request.url))

        has_purchased = db.session.query(OrderItem.id).join(Order).filter(
            Order.user_id == current_user.id,
            OrderItem.product_id == product_id,
            Order.status.in_(['pending', 'paid', 'shipped', 'delivered'])
        ).first() is not None

        if not has_purchased:
            flash('Вы можете оставить отзыв только на товар, который уже заказывали.', 'danger')
            return redirect(url_for('main.product_detail', product_id=product_id))

        existing_review = Review.query.filter_by(
            user_id=current_user.id, 
            product_id=product_id
        ).first()

        if existing_review:
            flash('Вы уже оставили отзыв на этот товар.', 'warning')
            return redirect(url_for('main.product_detail', product_id=product_id))

        review = Review(
            user_id=current_user.id,
            product_id=product_id,
            rating=form.rating.data,
            comment=form.comment.data.strip()
        )
        db.session.add(review)
        db.session.commit()

        flash('Спасибо за ваш отзыв!', 'success')
        return redirect(url_for('main.product_detail', product_id=product_id))

    # --- Загрузка данных для страницы ---
# --- Загрузка данных для страницы ---
    reviews = Review.query.filter_by(product_id=product_id)\
                         .order_by(Review.created_at.desc()).all()

    avg_rating = db.session.query(func.avg(Review.rating))\
                           .filter_by(product_id=product_id).scalar() or 0.0
    avg_rating = round(float(avg_rating), 1)
    review_count = len(reviews)

    # === Избранное для детальной страницы ===
    in_favorites = []
    if current_user.is_authenticated and hasattr(current_user, 'favorites'):
        in_favorites = [product.id for product in current_user.favorites]

    # === ПОХОЖИЕ ТОВАРЫ v7 — Жёсткий фильтр по категориям ===
    similar_products = []

    if product.image_features and product.categories:
        try:
            target_features = json.loads(product.image_features) if isinstance(product.image_features, str) else product.image_features

            product_category_ids = {cat.id for cat in product.categories}

            candidates = Product.query\
                .join(ProductCategory)\
                .filter(
                    Product.id != product.id,
                    Product.image_features.isnot(None),
                    ProductCategory.category_id.in_(product_category_ids)
                )\
                .limit(50).all()

            similarities = []
            for p in candidates:
                if p.image_features:
                    try:
                        p_features = json.loads(p.image_features) if isinstance(p.image_features, str) else p.image_features
                        visual_sim = cosine_similarity(target_features, p_features)

                        p_category_ids = {cat.id for cat in p.categories} if p.categories else set()
                        common = len(product_category_ids & p_category_ids)

                        score = visual_sim * 0.90 + (common * 0.40)

                        if product.price and p.price:
                            price_diff = abs(product.price - p.price) / max(product.price, p.price + 1)
                            score += (1 - price_diff) * 0.15

                        if score > 0.72:
                            similarities.append((p, score))

                    except:
                        continue

            similarities.sort(key=lambda x: x[1], reverse=True)
            similar_products = [item[0] for item in similarities[:8]]

        except Exception as e:
            print(f"[product_detail] Ошибка расчёта похожих товаров для {product.id}: {e}")

    return render_template('main/product_detail.html',
                           product=product,
                           reviews=reviews,
                           avg_rating=avg_rating,
                           review_count=review_count,
                           form=form,
                           in_favorites=in_favorites,      # ← ЭТО БЫЛО ГЛАВНОЕ ИСПРАВЛЕНИЕ
                           similar_products=similar_products)

# Вспомогательная функция для расчёта похожести
def cosine_similarity(vec1, vec2):
    if not vec1 or not vec2:
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    mag1 = sqrt(sum(a * a for a in vec1))
    mag2 = sqrt(sum(b * b for b in vec2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)
