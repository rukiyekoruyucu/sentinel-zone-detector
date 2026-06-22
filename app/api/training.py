"""
app/api/training.py — Model Eğitim API
=======================================
Endpoint'ler:
  POST /api/training/probe           → Video bilgilerini al (süre, FPS)
  POST /api/training/start           → Eğitimi arka planda başlat (model_name destekli)
  GET  /api/training/status          → Eğitim durumu (progress, log)
  POST /api/training/cancel          → Eğitimi durdur
  GET  /api/training/models          → Kayıtlı modellerin listesi
  POST /api/training/models/activate → Seçilen modeli aktif yap
  DELETE /api/training/models/<name> → Modeli sil (aktif değilse)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required

logger = logging.getLogger(__name__)

training_bp = Blueprint('training_api', __name__, url_prefix='/api/training')

# ─── Global eğitim durumu ──────────────────────────────────────────────────
_training_state = {
    "running":   False,
    "progress":  0,
    "message":   "Hazır",
    "logs":      [],
    "result":    None,    # son eğitim sonucu
    "thread":    None,
    "stop_event": None,
}
_state_lock = threading.Lock()


def _update_state(**kwargs):
    with _state_lock:
        _training_state.update(kwargs)


def _append_log(pct: int, msg: str):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {pct:3d}% — {msg}"
    logger.info(entry)
    with _state_lock:
        _training_state["progress"] = pct
        _training_state["message"]  = msg
        _training_state["logs"].append(entry)
        if len(_training_state["logs"]) > 200:
            _training_state["logs"] = _training_state["logs"][-200:]


# ─── Yardımcı: saved_models klasörü ───────────────────────────────────────
def _saved_models_dir() -> Path:
    from inference.xg import xg_config as cfg
    d = Path(cfg.SAVED_MODELS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _active_model_path() -> Path:
    from inference.xg import xg_config as cfg
    return Path(cfg.ENSEMBLE_SAVE_PATH)


def _safe_name(name: str) -> str:
    """Model adını dosya sistemi için güvenli hale getir."""
    import re
    name = name.strip()
    name = re.sub(r'[^\w\s\-]', '', name, flags=re.UNICODE)
    name = re.sub(r'\s+', '_', name)
    return name[:64] or "model"


# ───────────────────────────────────────────────────────────────────────────
# Endpoints
# ───────────────────────────────────────────────────────────────────────────

@training_bp.route('/probe', methods=['POST'])
@login_required
def probe():
    """
    Video dosyasından bilgi al (süre, FPS, boyut).
    Body: { "video_path": "..." }
    """
    data       = request.get_json() or {}
    video_path = data.get("video_path", "").strip()

    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "Dosya bulunamadı veya yol boş"}), 400

    try:
        from inference.xg.train_pipeline import get_video_info
        info = get_video_info(video_path)
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@training_bp.route('/start', methods=['POST'])
@login_required
def start_training():
    """
    Eğitimi arka planda başlat.

    Body:
    {
      "video_path":     "/path/to/video.avi",
      "model_name":     "Giriş Kapısı",       ← isteğe bağlı
      "normal_start":   0,
      "normal_end":     20,
      "anomaly_start":  53,
      "anomaly_end":    73,
      "frame_skip":     1,
      "warmup_frames":  60,
      "max_samples":    2000,
      "augmentation_multiplier": 5,
      "threshold":      0.65
    }
    """
    with _state_lock:
        if _training_state["running"]:
            return jsonify({"error": "Eğitim zaten devam ediyor"}), 409

    data = request.get_json() or {}

    video_path    = data.get("video_path", "").strip()
    model_name    = data.get("model_name", "").strip()
    normal_start  = float(data.get("normal_start", 0))
    normal_end    = float(data.get("normal_end", 20))
    anomaly_start = float(data.get("anomaly_start", 53))
    anomaly_end   = float(data.get("anomaly_end", 73))

    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "Geçerli bir video yolu belirtin"}), 400

    if normal_end <= normal_start:
        return jsonify({"error": "Normal bitiş > normal başlangıç olmalı"}), 400
    if anomaly_end <= anomaly_start:
        return jsonify({"error": "Anomali bitiş > anomali başlangıç olmalı"}), 400

    # Model adı yoksa otomatik üret
    if not model_name:
        model_name = datetime.now().strftime("model_%Y%m%d_%H%M%S")
    safe_name = _safe_name(model_name)

    params = {
        "frame_skip":              int(data.get("frame_skip", 1)),
        "warmup_frames":           int(data.get("warmup_frames", 60)),
        "max_samples":             int(data.get("max_samples", 2000)),
        "augmentation_multiplier": int(data.get("augmentation_multiplier", 5)),
        "threshold":               float(data.get("threshold", 0.65)),
        "model_path":              str(_active_model_path()),
    }

    stop_event = threading.Event()
    _update_state(
        running=True, progress=0, message="Başlatılıyor...",
        logs=[], result=None, stop_event=stop_event,
    )

    app = current_app._get_current_object()

    def _worker():
        try:
            with app.app_context():
                from inference.xg.train_pipeline import run_training
                result = run_training(
                    video_path,
                    normal_start, normal_end,
                    anomaly_start, anomaly_end,
                    params,
                    progress_cb=_append_log,
                    stop_event=stop_event,
                )

                # Model başarıyla eğitildiyse kaydet + XGDetector yeniden yükle
                if result.get("success"):
                    # 1) saved_models'e isimli kopya
                    active = _active_model_path()
                    if active.exists():
                        saved_dir = _saved_models_dir()
                        dest_pkl  = saved_dir / f"{safe_name}.pkl"
                        shutil.copy2(str(active), str(dest_pkl))

                        # Meta veri JSON
                        meta = {
                            "name":         model_name,
                            "safe_name":    safe_name,
                            "created_at":   datetime.now().isoformat(),
                            "video_path":   video_path,
                            "metrics":      result.get("metrics", {}),
                            "params": {
                                "normal":  f"{normal_start}–{normal_end} sn",
                                "anomaly": f"{anomaly_start}–{anomaly_end} sn",
                                "threshold": params["threshold"],
                            }
                        }
                        meta_path = saved_dir / f"{safe_name}.json"
                        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
                        _append_log(100, f"✓ Model kaydedildi: {safe_name}")

                    # 2) XGDetector güncelle
                    if hasattr(app, "xg_detector"):
                        try:
                            if app.xg_detector is None:
                                from inference.xg_detector import XGDetector
                                app.xg_detector = XGDetector()
                            else:
                                app.xg_detector.reload_model()
                            _append_log(100, "✓ XGDetector güncellendi — canlı analiz hazır")
                        except Exception as e:
                            logger.warning(f"[Training] XGDetector reload hatası: {e}")

                    result["model_name"]  = model_name
                    result["model_saved"] = safe_name

                _update_state(running=False, result=result)

        except Exception as e:
            _update_state(running=False, result={"success": False, "message": str(e)})
            _append_log(0, f"HATA: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="train-thread")
    t.start()
    _update_state(thread=t)

    return jsonify({"status": "started"})


@training_bp.route('/status', methods=['GET'])
@login_required
def get_status():
    """Eğitim durumunu döndür."""
    with _state_lock:
        state = {
            "running":  _training_state["running"],
            "progress": _training_state["progress"],
            "message":  _training_state["message"],
            "logs":     _training_state["logs"][-50:],   # son 50 satır
            "result":   _training_state["result"],
        }
    return jsonify(state)


@training_bp.route('/cancel', methods=['POST'])
@login_required
def cancel_training():
    """Çalışan eğitimi durdur."""
    with _state_lock:
        ev = _training_state.get("stop_event")
        if not _training_state["running"] or ev is None:
            return jsonify({"status": "not_running"}), 400
        ev.set()

    _append_log(0, "İptal isteği gönderildi...")
    return jsonify({"status": "cancelling"})


# ─── Model Yönetimi ────────────────────────────────────────────────────────

@training_bp.route('/models', methods=['GET'])
@login_required
def list_models():
    """Kayıtlı model listesini döndür."""
    saved_dir  = _saved_models_dir()
    active_pkl = _active_model_path()

    models = []
    for meta_file in sorted(saved_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
            pkl  = saved_dir / f"{meta['safe_name']}.pkl"
            # Aktif modelle aynı mı?
            is_active = False
            if active_pkl.exists() and pkl.exists():
                try:
                    is_active = active_pkl.stat().st_size == pkl.stat().st_size
                except Exception:
                    pass
            meta["is_active"] = is_active
            meta["file_size"] = pkl.stat().st_size if pkl.exists() else 0
            models.append(meta)
        except Exception:
            continue

    return jsonify({"models": models})


@training_bp.route('/models/activate', methods=['POST'])
@login_required
def activate_model():
    """Seçilen modeli aktif ensemble_model.pkl olarak kopyala + XGDetector reload."""
    data      = request.get_json() or {}
    safe_name = data.get("safe_name", "").strip()
    if not safe_name:
        return jsonify({"error": "safe_name gerekli"}), 400

    saved_dir = _saved_models_dir()
    src       = saved_dir / f"{safe_name}.pkl"
    if not src.exists():
        return jsonify({"error": f"Model bulunamadı: {safe_name}"}), 404

    dest = _active_model_path()
    try:
        shutil.copy2(str(src), str(dest))
    except Exception as e:
        return jsonify({"error": f"Kopyalama hatası: {e}"}), 500

    # XGDetector'ı yeniden yükle
    try:
        from flask import current_app as app
        if hasattr(app, "xg_detector") and app.xg_detector:
            app.xg_detector.reload_model()
        elif hasattr(app, "xg_detector"):
            from inference.xg_detector import XGDetector
            app.xg_detector = XGDetector()
    except Exception as e:
        logger.warning(f"[Activate] XGDetector reload hatası: {e}")

    return jsonify({"status": "activated", "model": safe_name})


@training_bp.route('/models/<safe_name>', methods=['DELETE'])
@login_required
def delete_model(safe_name):
    """Modeli sil (aktif modele dokunmaz)."""
    saved_dir  = _saved_models_dir()
    active_pkl = _active_model_path()

    pkl  = saved_dir / f"{safe_name}.pkl"
    meta = saved_dir / f"{safe_name}.json"

    if not pkl.exists():
        return jsonify({"error": "Model bulunamadı"}), 404

    # Aktif modelle aynı dosya mı kontrol et
    if active_pkl.exists():
        try:
            if active_pkl.stat().st_size == pkl.stat().st_size:
                # Aynı boyutta → aktif model olabilir, uyar
                force = request.args.get("force", "false").lower() == "true"
                if not force:
                    return jsonify({
                        "warning": "Bu model şu an aktif görünüyor. Silmek için ?force=true ekleyin.",
                        "is_active": True
                    }), 409
        except Exception:
            pass

    try:
        if pkl.exists():  pkl.unlink()
        if meta.exists(): meta.unlink()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "deleted", "model": safe_name})
