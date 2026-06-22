from datetime import datetime
from app.extensions import db
import json


class Camera(db.Model):
    __tablename__ = 'cameras'

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(128), nullable=False)
    source_type  = db.Column(db.String(16),  nullable=False)  # 'rtsp' | 'file' | 'webcam'
    source_value = db.Column(db.String(512), nullable=True)   # RTSP URL veya dosya yolu
    description  = db.Column(db.String(256), nullable=True)
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    zone_templates = db.relationship('ZoneTemplate', backref='camera',
                                     lazy='dynamic', cascade='all, delete-orphan')
    sessions       = db.relationship('Session', backref='camera', lazy='dynamic')

    def __repr__(self) -> str:
        return f'<Camera {self.name} [{self.source_type}]>'


class ZoneTemplate(db.Model):
    __tablename__ = 'zone_templates'

    id           = db.Column(db.Integer, primary_key=True)
    camera_id    = db.Column(db.Integer, db.ForeignKey('cameras.id'), nullable=False)
    name         = db.Column(db.String(128), nullable=False, default='Varsayılan Zone')
    polygon_json = db.Column(db.Text, nullable=False)   # JSON array [[x,y], ...]
    is_default   = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def polygon(self):
        return json.loads(self.polygon_json)

    @polygon.setter
    def polygon(self, points):
        self.polygon_json = json.dumps(points)

    def __repr__(self) -> str:
        return f'<ZoneTemplate {self.name} cam={self.camera_id}>'
