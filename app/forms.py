from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, BooleanField, SubmitField,
    SelectField, TextAreaField, FloatField, IntegerField,
    SelectMultipleField, FileField
)
from wtforms.validators import (
    DataRequired, Email, EqualTo, Length, Optional,
    NumberRange, ValidationError
)
from flask_wtf.file import FileAllowed

from app.models import User


class RegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField('Повторите пароль', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Зарегистрироваться')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Этот email уже зарегистрирован')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    remember = BooleanField('Запомнить меня')
    submit = SubmitField('Войти')


class TwoFactorForm(FlaskForm):
    code = StringField('Код из email', validators=[DataRequired(), Length(min=6, max=6)])
    submit = SubmitField('Подтвердить')


class ResetPasswordRequestForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Отправить ссылку')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('Новый пароль', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField('Повторите пароль', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Сбросить пароль')


class ProfileForm(FlaskForm):
    first_name = StringField('Имя', validators=[Optional(), Length(max=100)])
    last_name  = StringField('Фамилия', validators=[Optional(), Length(max=100)])
    phone      = StringField('Телефон (будет зашифрован)', validators=[Optional()])
    address    = StringField('Адрес (будет зашифрован)', validators=[Optional()])
    submit     = SubmitField('Сохранить изменения')


class ChangePasswordForm(FlaskForm):
    old_password = PasswordField('Текущий пароль', validators=[DataRequired()])
    new_password = PasswordField('Новый пароль', validators=[DataRequired(), Length(min=8)])
    new_password2 = PasswordField(
        'Повторите новый пароль',
        validators=[DataRequired(), EqualTo('new_password', message='Пароли должны совпадать')]
    )
    submit = SubmitField('Сменить пароль')


class CheckoutForm(FlaskForm):
    address = StringField('Адрес доставки', validators=[DataRequired(), Length(max=500)])
    payment_method = SelectField('Способ оплаты', choices=[
        ('card', 'Банковская карта (симуляция)'),
        ('cash', 'Оплата при получении')
    ], validators=[DataRequired()])
    submit = SubmitField('Оформить заказ')


class ProductForm(FlaskForm):
    name = StringField(
        'Название товара',
        validators=[
            DataRequired(message='Название обязательно'),
            Length(min=3, max=200, message='Название должно быть от 3 до 200 символов')
        ]
    )
    description = TextAreaField(
        'Описание',
        validators=[Optional(), Length(max=5000)]
    )
    price = FloatField(
        'Цена (₽)',
        validators=[DataRequired(), NumberRange(min=0.01)]
    )
    quantity_available = IntegerField(
        'Количество на складе',
        validators=[DataRequired(), NumberRange(min=0)]
    )
    categories = SelectMultipleField('Категории', coerce=int, validators=[Optional()])
    image = FileField('Изображение товара', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'])])
    submit = SubmitField('Сохранить изменения')


class ReviewForm(FlaskForm):
    rating = IntegerField('Оценка (от 1 до 5)', validators=[
        DataRequired(), NumberRange(min=1, max=5)
    ])
    comment = TextAreaField('Ваш отзыв', validators=[
        DataRequired(), Length(min=10, max=1000)
    ])
    submit = SubmitField('Опубликовать отзыв')
