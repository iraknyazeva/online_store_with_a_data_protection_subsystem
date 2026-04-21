from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_session import Session
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect
import os

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
login_manager = LoginManager()
session = Session()
csrf = CSRFProtect()

@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return User.query.get(int(user_id))


def create_app():
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static',
                static_url_path='/static')

    # === ОСНОВНЫЕ НАСТРОЙКИ ===
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError("SECRET_KEY не найден в .env файле!")

    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # === SESSION ===
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(__file__), '..', 'flask_session')
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True

    # Инициализация расширений
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    session.init_app(app)
    csrf.init_app(app)

    # Декораторы
    from app.decorators import buyer_required, admin_required
    app.jinja_env.globals['buyer_required'] = buyer_required
    app.jinja_env.globals['admin_required'] = admin_required

    # Регистрация blueprint'ов
    from app.auth import auth_bp
    from app.main import main_bp
    from app.buyer import buyer_bp
    from app.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(buyer_bp)
    app.register_blueprint(admin_bp)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Пожалуйста, войдите, чтобы увидеть эту страницу.'
    login_manager.login_message_category = 'info'

    @app.route('/')
    def index():
        return render_template('index.html')
    
    from app.commands.fill_image_features import fill_image_features
    app.cli.add_command(fill_image_features)
    
    return app
