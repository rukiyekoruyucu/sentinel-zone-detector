import os
from pathlib import Path
from flask import Flask
from app.extensions import db, migrate, login_mgr, socketio
from config import config


def create_app(env: str = None) -> Flask:
    env = env or os.getenv('FLASK_ENV', 'default')
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config[env])

    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    Path(app.config['SNAPSHOT_FOLDER']).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_mgr.init_app(app)
    socketio.init_app(app,
                      async_mode=app.config['SOCKETIO_ASYNC_MODE'],
                      cors_allowed_origins='*')

    # User loader
    from app.models.user import User

    @login_mgr.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Modelleri yükle
    _load_models(app)

    # Blueprint kayıt
    from app.auth import auth_bp
    from app.api import sessions_bp, reports_bp, cameras_bp, upload_bp, filebrowser_bp, training_bp
    from app.admin import admin_bp
    from app.views import dashboard_bp, session_view_bp, training_view_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(cameras_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(filebrowser_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(session_view_bp)
    app.register_blueprint(training_view_bp)

    # SocketIO event handlers
    _register_socketio_events()

    return app


def _load_models(app: Flask):
    """Alan İhlal (ZoneDetector) ve İstenmeyen Obje (XGDetector) modellerini yükle."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    # Alan İhlal Algoritması — Detector + PoseEstimator
    try:
        from inference.detector import Detector
        from inference.pose_estimator import PoseEstimator
        app.detector = Detector(
            model_path=str(app.config['DET_MODEL']),
            score_thr=app.config['DET_SCORE_THR'],
            engine='openvino',
        )
        app.pose_estimator = PoseEstimator(
            model_path=str(app.config['POSE_MODEL']),
            kpt_thr=app.config['POSE_KPT_THR'],
            engine='openvino',
        )
        app.logger.info('✓ Alan İhlal modelleri yüklendi (YOLO11n + RTMPose-T).')
    except Exception as e:
        app.logger.warning(f'⚠ Alan İhlal modelleri yüklenemedi: {e}')
        app.detector       = None
        app.pose_estimator = None

    # İstenmeyen Obje Algoritması — XGBoost + MOG2 + HOG
    try:
        from inference.xg_detector import XGDetector
        app.xg_detector = XGDetector()
        app.logger.info(
            f'✓ İstenmeyen Obje modeli yüklendi (ready={app.xg_detector.is_ready()}).'
        )
    except Exception as e:
        app.logger.warning(f'⚠ İstenmeyen Obje modeli yüklenemedi: {e}')
        app.xg_detector = None


def _register_socketio_events():
    from app.extensions import socketio
    from flask_socketio import join_room, leave_room

    @socketio.on('join')
    def on_join(data):
        sid = data.get('session_id')
        if sid:
            join_room(f'session_{sid}')

    @socketio.on('leave')
    def on_leave(data):
        sid = data.get('session_id')
        if sid:
            leave_room(f'session_{sid}')
