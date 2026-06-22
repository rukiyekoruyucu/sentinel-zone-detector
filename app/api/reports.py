from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models.session import Session
from app.models.violation import ViolationEvent
from app.stream.manager import stream_manager

reports_bp = Blueprint('reports_api', __name__, url_prefix='/api/reports')


@reports_bp.route('/stats')
@login_required
def stats():
    uid = current_user.id
    today  = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=6)

    total_sessions   = Session.query.filter_by(user_id=uid).count()
    active_sessions  = stream_manager.active_count()
    today_violations = db.session.query(func.count(ViolationEvent.id))\
        .join(Session).filter(
            Session.user_id == uid,
            ViolationEvent.timestamp >= today,
        ).scalar() or 0
    week_violations = db.session.query(func.count(ViolationEvent.id))\
        .join(Session).filter(
            Session.user_id == uid,
            ViolationEvent.timestamp >= week_ago,
        ).scalar() or 0

    # Weekly breakdown per algo (last 7 days)
    labels = []
    weekly_zd = []
    weekly_xg = []
    day_names = ['Pzt','Sal','Çar','Per','Cum','Cmt','Paz']
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        labels.append(day_names[d.weekday()])
        next_d = d + timedelta(days=1)
        zd_cnt = db.session.query(func.count(ViolationEvent.id))\
            .join(Session).filter(
                Session.user_id == uid,
                Session.algorithm_type == 'zone_detector',
                ViolationEvent.timestamp >= d,
                ViolationEvent.timestamp < next_d,
            ).scalar() or 0
        xg_cnt = db.session.query(func.count(ViolationEvent.id))\
            .join(Session).filter(
                Session.user_id == uid,
                Session.algorithm_type == 'xg_detector',
                ViolationEvent.timestamp >= d,
                ViolationEvent.timestamp < next_d,
            ).scalar() or 0
        weekly_zd.append(zd_cnt)
        weekly_xg.append(xg_cnt)

    return jsonify({
        'total_sessions':   total_sessions,
        'active_sessions':  active_sessions,
        'today_violations': today_violations,
        'week_violations':  week_violations,
        'weekly_labels':    labels,
        'weekly_zd':        weekly_zd,
        'weekly_xg':        weekly_xg,
    })


@reports_bp.route('/violations')
@login_required
def violations():
    uid      = current_user.id
    limit    = min(int(request.args.get('limit', 200)), 1000)
    algo     = request.args.get('algo')
    from_dt  = request.args.get('from_dt')
    to_dt    = request.args.get('to_dt')
    sess_id  = request.args.get('session_id', type=int)

    q = db.session.query(ViolationEvent, Session)\
        .join(Session, ViolationEvent.session_id == Session.id)\
        .filter(Session.user_id == uid)

    if algo:     q = q.filter(Session.algorithm_type == algo)
    if sess_id:  q = q.filter(Session.id == sess_id)
    if from_dt:
        try: q = q.filter(ViolationEvent.timestamp >= datetime.fromisoformat(from_dt))
        except ValueError: pass
    if to_dt:
        try: q = q.filter(ViolationEvent.timestamp <= datetime.fromisoformat(to_dt + 'T23:59:59'))
        except ValueError: pass

    rows = q.order_by(ViolationEvent.timestamp.desc()).limit(limit).all()

    violations_list = [{
        'id':             v.id,
        'session_id':     s.id,
        'session_label':  s.session_label,
        'algorithm_type': s.algorithm_type,
        'timestamp':      v.timestamp.isoformat(),
        'person_count':   v.person_count,
        'snapshot_path':  v.snapshot_path,
    } for v, s in rows]

    # Aggregate stats
    total = len(violations_list)
    zd_c  = sum(1 for v in violations_list if v['algorithm_type'] == 'zone_detector')
    xg_c  = sum(1 for v in violations_list if v['algorithm_type'] == 'xg_detector')
    unique_sess = len(set(v['session_id'] for v in violations_list))

    return jsonify({
        'violations': violations_list,
        'stats': {
            'total':         total,
            'zone_detector': zd_c,
            'xg_detector':   xg_c,
            'sessions':      unique_sess,
        },
    })


@reports_bp.route('/sessions')
@login_required
def sessions_summary():
    """Her session için özet istatistikleri döndür."""
    uid  = current_user.id
    algo = request.args.get('algo')

    q = Session.query.filter_by(user_id=uid)
    if algo:
        q = q.filter_by(algorithm_type=algo)
    sessions = q.order_by(Session.created_at.desc()).limit(200).all()

    result = []
    for s in sessions:
        vcount = s.violations.count()
        result.append({
            'id':             s.id,
            'session_label':  s.session_label,
            'algorithm_type': s.algorithm_type,
            'source_type':    s.source_type,
            'status':         s.status,
            'violation_count': vcount,
            'duration_seconds': s.duration_seconds,
            'started_at':     s.started_at.isoformat() if s.started_at else None,
            'ended_at':       s.ended_at.isoformat() if s.ended_at else None,
            'created_at':     s.created_at.isoformat(),
        })

    return jsonify({'sessions': result, 'total': len(result)})

