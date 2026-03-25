from flask import Flask
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from config import Config

mysql = MySQL()
bcrypt = Bcrypt()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    mysql.init_app(app)
    bcrypt.init_app(app)

    from .routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app
