from datetime import datetime
from app.extensions import db
import json


class Session(db.Model):
    __tablename__ = 'sessions'

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    camera_id     = db.Column(db.Integer, db.ForeignKey('cameras.id'), nullable=True)

    # Algoritma tipi: 'zone_detector' | 'xg_detector'
    algorithm_type = db.Column(db.String(32), default='zone_detector', nullable=False)
    session_label  = db.Column(db.String(128), nullable=True)  # kullanıcı tanımlı etiket

    # Video kaynağı
    source_type   = db.Column(db.String(16), nullable=False)   # 'rtsp' | 'file' | 'webcam'
    source_value  = db.Column(db.String(512), nullable=True)

    # Zone (zone_detector için)
    zone_json     = db.Column(db.Text, nullable=True)

    # ZoneDetector model ayarları
    engine_type   = db.Column(db.String(16), default='openvino')
    det_score_thr = db.Column(db.Float, default=0.35)
    kpt_thr       = db.Column(db.Float, default=0.30)

    # XG Detector ayarları (JSON blob)
    xg_config_json = db.Column(db.Text, nullable=True)

    # Durum
    status        = db.Column(db.String(16), default='pending')
    started_at    = db.Column(db.DateTime, nullable=True)
    ended_at      = db.Column(db.DateTime, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    violations    = db.relationship('ViolationEvent', backref='session',
                                    lazy='dynamic', cascade='all, delete-orphan')

    @property
    def zone(self):
        return json.loads(self.zone_json) if self.zone_json else None

    @zone.setter
    def zone(self, points):
        self.zone_json = json.dumps(points) if points else None

    @property
    def xg_config(self):
        defaults = {
            'confidence_thr': 0.45,
            'alarm_cooldown': 5,
            'target_classes': [],
            'min_object_area': 500,
        }
        if self.xg_config_json:
            defaults.update(json.loads(self.xg_config_json))
        return defaults

    @xg_config.setter
    def xg_config(self, cfg):
        self.xg_config_json = json.dumps(cfg) if cfg else None

    @property
    def duration_seconds(self):
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return None

    @property
    def violation_count(self):
        return self.violations.count()

    def to_dict(self):
        return {
            'id':             self.id,
            'algorithm_type': self.algorithm_type,
            'session_label':  self.session_label,
            'source_type':    self.source_type,
            'source_value':   self.source_value,
            'status':         self.status,
            'zone':           self.zone,
            'xg_config':      self.xg_config if self.algorithm_type == 'xg_detector' else None,
            'det_score_thr':  self.det_score_thr,
            'kpt_thr':        self.kpt_thr,
            'started_at':     self.started_at.isoformat() if self.started_at else None,
            'ended_at':       self.ended_at.isoformat() if self.ended_at else None,
            'duration_seconds': self.duration_seconds,
            'violation_count':  self.violation_count,
            'created_at':     self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<Session {self.id} [{self.algorithm_type}|{self.status}]>'
