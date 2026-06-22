import logging
import os
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, Response, current_app
from flask_login import login_required, current_user

from app.extensions import db
from app.models.session import Session
from app.models.violation import ViolationEvent
from app.stream.manager import stream_manager

sessions_bp = Blueprint('sessions_api', __name__, url_prefix='/api/sessions')
logger = logging.getLogger(__name__)


@sessions_bp.route('', methods=['POST'])
@login_required
def create_session():
    data = request.get_json() or {}

    source_type    = data.get('source_type')
    source_value   = data.get('source_value', '')
    algorithm_type = data.get('algorithm_type', 'zone_detector')
    session_label_raw = data.get('session_label')
    session_label  = session_label_raw.strip() if session_label_raw else None

    if source_type not in ('rtsp', 'file', 'webcam'):
        return jsonify({'error': 'Geçersiz source_type'}), 400
    if algorithm_type not in ('zone_detector', 'xg_detector'):
        return jsonify({'error': 'Geçersiz algorithm_type'}), 400

    # Dosya kaynağı — yerel yol mu yoksa yüklenen dosya mı?
    if source_type == 'file':
        if not source_value:
            return jsonify({'error': 'Dosya yolu/yükleme gerekli'}), 400
        p = Path(source_value)
        if not p.exists():
            return jsonify({'error': f'Dosya bulunamadı: {source_value}'}), 400
        if not p.is_file():
            return jsonify({'error': 'Bu bir dosya değil'}), 400
        source_value = str(p.resolve())

    session = Session(
        user_id        = current_user.id,
        camera_id      = data.get('camera_id'),
        algorithm_type = algorithm_type,
        session_label  = session_label,
        source_type    = source_type,
        source_value   = source_value,
        det_score_thr  = float(data.get('det_score_thr', current_app.config['DET_SCORE_THR'])),
        kpt_thr        = float(data.get('kpt_thr', current_app.config['POSE_KPT_THR'])),
        status         = 'pending',
    )

    if algorithm_type == 'xg_detector':
        session.xg_config = {
            'confidence_thr':  float(data.get('xg_confidence_thr', 0.45)),
            'alarm_cooldown':  int(data.get('xg_alarm_cooldown', 5)),
            'target_classes':  data.get('xg_target_classes', []),
            'min_object_area': int(data.get('xg_min_area', 500)),
            'model_name':      data.get('xg_model_name', ''),   # seçilen kayıtlı model
        }

    db.session.add(session)
    db.session.commit()
    return jsonify(session.to_dict()), 201



@sessions_bp.route('/<int:session_id>/zone', methods=['POST'])
@login_required
def set_zone(session_id):
    session = Session.query.get_or_404(session_id)
    data    = request.get_json() or {}
    polygon = data.get('polygon', [])

    # Boş polygon = zone temizle
    if not polygon:
        session.zone = None
        db.session.commit()
        s = stream_manager.get_session(session_id)
        if s:
            s.zone = None
        return jsonify({'status': 'ok', 'polygon': []})

    if len(polygon) < 3:
        return jsonify({'error': 'En az 3 nokta gerekli'}), 400

    # Frontend normalize koordinat gönderiyorsa ([0,1] aralığı) piksel'e çevir
    # Backend video frame boyutu: FRAME_W=640, FRAME_H=480 (StreamSession sabit)
    FRAME_W = 640
    FRAME_H = 480
    is_normalized = data.get('normalized', False)

    if is_normalized:
        # Normalize → piksel dönüşümü
        pixel_polygon = [
            [round(pt[0] * FRAME_W), round(pt[1] * FRAME_H)]
            for pt in polygon
        ]
    else:
        # Eski format: piksel koordinatları doğrudan
        pixel_polygon = [[int(pt[0]), int(pt[1])] for pt in polygon]

    session.zone = pixel_polygon
    db.session.commit()

    s = stream_manager.get_session(session_id)
    if s:
        import numpy as np
        s.zone = np.array(pixel_polygon, dtype=np.int32)

    return jsonify({'status': 'ok', 'polygon': pixel_polygon})


@sessions_bp.route('/<int:session_id>/start', methods=['POST'])
@login_required
def start_session(session_id):
    session = Session.query.get_or_404(session_id)
    if session.status == 'active':
        return jsonify({'error': 'Session zaten aktif'}), 400

    det  = current_app.detector
    pose = current_app.pose_estimator
    xg   = current_app.xg_detector

    # XG Detector — seçilen kayıtlı modeli yükle
    if session.algorithm_type == 'xg_detector':
        model_name = (session.xg_config or {}).get('model_name', '')
        if model_name:
            try:
                from inference.xg import xg_config as cfg
                from pathlib import Path as _Path
                import shutil as _shutil
                from inference.xg_detector import XGDetector as _XGD
                saved = _Path(cfg.SAVED_MODELS_DIR) / f"{model_name}.pkl"
                if saved.exists():
                    # Bu session için geçici bir XGDetector örneği oluştur
                    # aktif pkl'i geçici değiştir → yeni örnek oluştur → geri yükle
                    active = _Path(cfg.ENSEMBLE_SAVE_PATH)
                    backup = active.with_suffix('.bak.pkl')
                    _shutil.copy2(str(active), str(backup))
                    _shutil.copy2(str(saved), str(active))
                    try:
                        xg = _XGD()
                    finally:
                        _shutil.copy2(str(backup), str(active))
                        backup.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"[Session] Seçilen model yüklenemedi ({model_name}): {e}")

    stream_manager.start_session(
        session_id      = session.id,
        source_type     = session.source_type,
        source_value    = session.source_value,
        zone            = session.zone,
        algorithm_type  = session.algorithm_type,
        detector        = det,
        pose_estimator  = pose,
        xg_detector     = xg,
        xg_config       = session.xg_config,
        snapshot_folder = Path(current_app.config['SNAPSHOT_FOLDER']),
        det_score_thr   = session.det_score_thr,
        kpt_thr         = session.kpt_thr,
    )

    session.status     = 'active'
    session.started_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'status': 'started', 'session_id': session.id})


@sessions_bp.route('/<int:session_id>/stop', methods=['POST'])
@login_required
def stop_session(session_id):
    session = Session.query.get_or_404(session_id)
    stream_manager.stop_session(session_id)
    session.status   = 'stopped'
    session.ended_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'status': 'stopped'})


@sessions_bp.route('/<int:session_id>/stream')
@login_required
def stream(session_id):
    def generate():
        try:
            import eventlet
            _sleep = eventlet.sleep
        except ImportError:
            import time as _t
            _sleep = _t.sleep

        last_frame = None
        while True:
            s = stream_manager.get_session(session_id)
            if s is None:
                break           # Session durduruldu — generate'i bitir
            frame = s.latest_frame
            if frame and frame is not last_frame:
                last_frame = frame
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Cache-Control: no-cache\r\n\r\n' + frame + b'\r\n')
            _sleep(0.025)       # ~40 fps poll (hızlandırıldı)

    resp = Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma']        = 'no-cache'
    return resp



@sessions_bp.route('/<int:session_id>', methods=['GET'])
@login_required
def get_session(session_id):
    session = Session.query.get_or_404(session_id)
    return jsonify(session.to_dict())


@sessions_bp.route('', methods=['GET'])
@login_required
def list_sessions():
    page = request.args.get('page', 1, type=int)
    algo = request.args.get('algorithm', None)
    q    = Session.query.filter_by(user_id=current_user.id)
    if algo:
        q = q.filter_by(algorithm_type=algo)
    sessions = q.order_by(Session.created_at.desc()).limit(50).all()
    return jsonify([s.to_dict() for s in sessions])


@sessions_bp.route('/<int:session_id>', methods=['DELETE'])
@login_required
def delete_session(session_id):
    """Session ve tüm ilişkili verileri sil (snapshot dosyaları dahil)."""
    session = Session.query.get_or_404(session_id)
    if session.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Yetkisiz'}), 403

    # Aktifse önce stream'i durdur
    if session.status == 'active':
        stream_manager.stop_session(session_id)

    # Snapshot dosyalarını diskten sil
    try:
        snap_folder = Path(current_app.config['SNAPSHOT_FOLDER'])
        for v in session.violations:
            if v.snapshot_path:
                snap_file = snap_folder / v.snapshot_path
                if snap_file.exists():
                    snap_file.unlink()
    except Exception as e:
        logger.warning(f"[DeleteSession] Snapshot silinemedi: {e}")

    db.session.delete(session)
    db.session.commit()
    return jsonify({'status': 'deleted', 'session_id': session_id})


@sessions_bp.route('/snapshots/<path:filename>')
@login_required
def snapshot(filename):
    from flask import send_from_directory
    import os
    folder = current_app.config['SNAPSHOT_FOLDER']
    return send_from_directory(os.path.abspath(folder), filename)


@sessions_bp.route('/<int:session_id>/preview_frame')
@login_required
def preview_frame(session_id):
    """
    Videonun 3. saniyesinden bir kare döner (zone çizim önizlemesi için).
    JPEG formatında döner.
    """
    import cv2
    import numpy as np
    from flask import send_file
    import io

    session = Session.query.get_or_404(session_id)

    if session.source_type != 'file' or not session.source_value:
        return jsonify({'error': 'Yalnızca dosya kaynakları için önizleme mevcut'}), 400

    try:
        cap = cv2.VideoCapture(str(session.source_value))
        if not cap.isOpened():
            return jsonify({'error': 'Video açılamadı'}), 400

        fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        target_frame = int(fps * 3)   # 3. saniye
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target_frame = min(target_frame, max(0, total - 1))

        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return jsonify({'error': 'Kare okunamadı'}), 400

        frame = cv2.resize(frame, (640, 480))
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return send_file(
            io.BytesIO(buf.tobytes()),
            mimetype='image/jpeg',
            as_attachment=False,
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500
