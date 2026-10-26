from flask import Flask
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from flask_mail import Mail
from config import Config


mysql = MySQL()
bcrypt = Bcrypt()
mail = Mail()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializa extensiones
    mysql.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)

    # Registra el blueprint de rutas
    from app.routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app