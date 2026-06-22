from datetime import datetime
from app.extensions import db


class ViolationEvent(db.Model):
    __tablename__ = 'violation_events'

    id            = db.Column(db.Integer, primary_key=True)
    session_id    = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    person_count  = db.Column(db.Integer, default=0)
    in_violation  = db.Column(db.Boolean, default=True)
    snapshot_path = db.Column(db.String(512), nullable=True)  # ihlal anı görüntüsü

    def to_dict(self):
        return {
            'id':           self.id,
            'session_id':   self.session_id,
            'timestamp':    self.timestamp.isoformat(),
            'person_count': self.person_count,
            'in_violation': self.in_violation,
            'snapshot_path': self.snapshot_path,
        }

    def __repr__(self) -> str:
        return f'<ViolationEvent session={self.session_id} t={self.timestamp}>'
