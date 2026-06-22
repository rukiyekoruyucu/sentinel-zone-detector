from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from functools import wraps
from app.extensions import db
from app.models.user import User
from app.models.camera import Camera
from app.models.session import Session
from app.stream.manager import stream_manager

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Yönetici yetkisi gerekli.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@admin_required
def index():
    from flask import current_app
    users   = User.query.order_by(User.id).all()
    cameras = Camera.query.all()
    det     = getattr(current_app, 'detector', None)
    xg      = getattr(current_app, 'xg_detector', None)
    return render_template('admin/index.html',
        users           = users,
        cameras         = cameras,
        has_detector    = det is not None,
        has_xg          = xg is not None and xg.is_ready(),
        xg_stub         = xg is not None and not xg.is_ready(),
        active_sessions = stream_manager.active_count(),
    )


@admin_bp.route('/users', methods=['POST'])
@admin_required
def create_user():
    u = User(
        username = request.form['username'].strip(),
        email    = request.form['email'].strip(),
        role     = request.form.get('role', 'user'),
    )
    u.set_password(request.form['password'])
    db.session.add(u); db.session.commit()
    flash('Kullanıcı oluşturuldu.', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash('Kendinizi silemezsiniz.', 'error')
        return redirect(url_for('admin.index'))
    u = User.query.get_or_404(user_id)
    db.session.delete(u); db.session.commit()
    flash('Kullanıcı silindi.', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/cameras', methods=['POST'])
@admin_required
def create_camera():
    c = Camera(
        name         = request.form['name'].strip(),
        source_type  = request.form['source_type'],
        source_value = request.form['source_value'].strip(),
    )
    db.session.add(c); db.session.commit()
    flash('Kamera eklendi.', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/cameras/<int:camera_id>/delete', methods=['POST'])
@admin_required
def delete_camera(camera_id):
    c = Camera.query.get_or_404(camera_id)
    db.session.delete(c); db.session.commit()
    flash('Kamera silindi.', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/cleanup/sessions', methods=['POST'])
@admin_required
def cleanup_sessions():
    stopped = Session.query.filter_by(status='stopped').all()
    for s in stopped:
        db.session.delete(s)
    db.session.commit()
    flash(f'{len(stopped)} session temizlendi.', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/cleanup/snapshots', methods=['POST'])
@admin_required
def cleanup_snapshots():
    import os
    from pathlib import Path
    from datetime import datetime, timedelta
    from flask import current_app
    days    = int(request.form.get('days', 30))
    folder  = Path(current_app.config['SNAPSHOT_FOLDER'])
    cutoff  = datetime.utcnow() - timedelta(days=days)
    removed = 0
    for f in folder.glob('snap_*.jpg'):
        if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            removed += 1
    flash(f'{removed} snapshot dosyası silindi (>{days} gün).', 'success')
    return redirect(url_for('admin.index'))
