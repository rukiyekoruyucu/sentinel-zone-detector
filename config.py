import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY           = os.getenv('SECRET_KEY', 'sentinel-change-me-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL',
                                        f'sqlite:///{BASE_DIR}/zonedetector.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER        = BASE_DIR / os.getenv('UPLOAD_FOLDER',   'uploads')
    SNAPSHOT_FOLDER      = BASE_DIR / os.getenv('SNAPSHOT_FOLDER', 'snapshots')
    MAX_CONTENT_LENGTH   = int(os.getenv('MAX_CONTENT_LENGTH', 524_288_000))  # 500 MB
    ALLOWED_EXTENSIONS   = {'mp4', 'avi', 'mov', 'mkv'}

    # ZoneDetector
    DET_MODEL            = BASE_DIR / os.getenv('DET_MODEL',  'models/ov/yolo11n.xml')
    POSE_MODEL           = BASE_DIR / os.getenv('POSE_MODEL', 'models/ov/rtmpose-t.xml')
    DET_SCORE_THR        = float(os.getenv('DET_SCORE_THR', 0.35))
    POSE_KPT_THR         = float(os.getenv('POSE_KPT_THR',  0.30))

    # XGDetector
    XG_MODEL             = BASE_DIR / os.getenv('XG_MODEL', 'models/ov/xg_detector.xml')
    XG_CONFIDENCE_THR    = float(os.getenv('XG_CONFIDENCE_THR', 0.45))

    SOCKETIO_ASYNC_MODE  = 'eventlet'


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'default':     DevelopmentConfig,
}
