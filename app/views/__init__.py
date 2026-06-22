from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from app.models.session import Session
from app.models.camera import Camera

dashboard_bp     = Blueprint('dashboard',     __name__)
session_view_bp  = Blueprint('session_view',  __name__)
training_view_bp = Blueprint('training_view', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    return render_template('dashboard/index.html')


@session_view_bp.route('/sessions/new')
@login_required
def new_session():
    cameras = Camera.query.filter_by(is_active=True).all()
    return render_template('session/new.html', cameras=cameras)


@session_view_bp.route('/sessions/<int:session_id>')
@login_required
def view_session(session_id):
    from app.models.violation import ViolationEvent
    session = Session.query.get_or_404(session_id)
    if session.user_id != current_user.id and not current_user.is_admin:
        return redirect(url_for('dashboard.index'))
    recent_violations = ViolationEvent.query.filter_by(session_id=session_id)\
        .order_by(ViolationEvent.timestamp.desc()).limit(30).all()
    return render_template('session/view.html',
                           session=session,
                           recent_violations=recent_violations)


@session_view_bp.route('/reports')
@login_required
def reports():
    return render_template('report/index.html')


@training_view_bp.route('/training')
@login_required
def training_index():
    """İstenmeyen Obje Algoritması model eğitim sayfası."""
    return render_template('training/index.html')
