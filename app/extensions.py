from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO

db        = SQLAlchemy()
migrate   = Migrate()
login_mgr = LoginManager()
socketio  = SocketIO()

login_mgr.login_view     = 'auth.login'
login_mgr.login_message  = 'Bu sayfaya erişmek için giriş yapmalısınız.'
