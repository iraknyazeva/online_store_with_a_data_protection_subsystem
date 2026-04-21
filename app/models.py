from . import db
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Enum, JSON, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from flask_login import UserMixin
import enum

class SearchHistory(db.Model):
    __tablename__ = 'search_history'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    query = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship('User', backref='search_history')

class UserRole(enum.Enum):
    buyer = "buyer"
    admin = "admin"

class OrderStatus(enum.Enum):
    pending    = "pending"
    processing = "processing"
    paid       = "paid"
    shipped    = "shipped"
    delivered  = "delivered"
    cancelled  = "cancelled"

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.buyer, nullable=False)
    first_name = Column(String(100))
    last_name  = Column(String(100))
    phone_encrypted = Column(Text)
    address_encrypted = Column(Text)
    account_active = Column(Boolean, default=True)  # ← переименовали
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime)
    preferences = Column(JSON, default=dict)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    orders = relationship('Order', back_populates='user', cascade='all, delete-orphan')
    favorites = relationship('Product', secondary='favorites', back_populates='favorited_by')
    cart_items = relationship('CartItem', back_populates='user', cascade='all, delete-orphan')
    reviews = relationship('Review', back_populates='user')

    __table_args__ = (Index('ix_users_email', 'email'),)

class Category(db.Model):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    parent_id = Column(Integer, ForeignKey('categories.id'), nullable=True)  # ← добавлено
    parent = relationship('Category', remote_side=[id], backref='children')  # ← иерархия

    products = relationship('Product', secondary='product_categories', back_populates='categories')

class Product(db.Model):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    price = Column(Float, nullable=False)
    quantity_available = Column(Integer, default=0, nullable=False)
    image_path = Column(String(255))
    image_features = Column(JSON)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    categories = relationship('Category', secondary='product_categories', back_populates='products')
    favorited_by = relationship('User', secondary='favorites', back_populates='favorites')
    order_items = relationship('OrderItem', back_populates='product')
    cart_items = relationship('CartItem', back_populates='product')
    reviews = relationship('Review', back_populates='product')

class ProductCategory(db.Model):
    __tablename__ = 'product_categories'
    product_id = Column(Integer, ForeignKey('products.id', ondelete='CASCADE'), primary_key=True)
    category_id = Column(Integer, ForeignKey('categories.id', ondelete='CASCADE'), primary_key=True)

class Favorite(db.Model):
    __tablename__ = 'favorites'
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id', ondelete='CASCADE'), primary_key=True)
    created_at = Column(DateTime, default=func.now())
    
    product = relationship('Product')

class Order(db.Model):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.pending, nullable=False)
    address_encrypted = Column(Text)
    total_price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship('User', back_populates='orders')
    items = relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    price_at_purchase = Column(Float, nullable=False)

    order = relationship('Order', back_populates='items')
    product = relationship('Product', back_populates='order_items')

class CartItem(db.Model):
    __tablename__ = 'cart_items'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=func.now())

    user = relationship('User', back_populates='cart_items')
    product = relationship('Product', back_populates='cart_items')

class Review(db.Model):
    __tablename__ = 'reviews'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    product_id = Column(Integer, ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    rating = Column(Integer, nullable=False)   # от 1 до 5
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship('User', back_populates='reviews')
    product = relationship('Product', back_populates='reviews')

    __table_args__ = (
        Index('ix_reviews_product_rating', 'product_id', 'rating'),
        # Один отзыв от одного пользователя на один товар
        Index('ix_unique_user_product_review', 'user_id', 'product_id', unique=True),
    )

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = Column(String(100), nullable=False)
    ip_address = Column(String(45))
    details = Column(JSON)
    timestamp = Column(DateTime, default=func.now())

    user = relationship('User')
