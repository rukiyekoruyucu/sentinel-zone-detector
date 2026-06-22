"""
StreamManager v4 — Yüksek Performanslı İki Katmanlı Pipeline
=============================================================

MİMARİ:
  • _loop        (socketio greenlet)  → frame okuma, encode, emit         ~30 fps
  • _infer_loop  (daemon OS thread)   → YOLO + RTMPose (ağır inference)  ~5-15 fps

Greenlet inference'ı BİTİRENE kadar BLOKE olmaz; her display frame'ine
en son hesaplanan sonuç overlay olarak çizilir.  Video asla grilenmez.

DÜZELTİLEN HATALAR:
  • eventlet greenlet'i bloke eden inference → daemon thread'e taşındı
  • zone/skeleton overlay BGR renk karışması → düzeltildi
  • Frame atlama (SKIP_INFERENCE_N) ile hız ayarı
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

from app.extensions import db, socketio

logger = logging.getLogger(__name__)


# ── Yardımcı: eventlet uyumlu sleep ──────────────────────────────────────────
def _get_sleep():
    try:
        import eventlet
        return eventlet.sleep
    except ImportError:
        return time.sleep


# ═════════════════════════════════════════════════════════════════════════════
class StreamSession:
    """
    Tek bir analiz oturumunu yönetir.

    Parametre kılavuzu
    ------------------
    INFER_EVERY : Kaç frame'de bir inference yapılsın (1 = her frame).
                  Bilgisayara göre ayarlayın:
                    – Güçlü makine  : 1–2
                    – Orta makine   : 3 (varsayılan)
                    – Zayıf makine  : 4–5
    STREAM_FPS  : Display greenlet'in hedef FPS'i.
    """

    _POSE_INPUT_SIZE = (192, 256)   # RTMPose-T giriş boyutu (W, H)
    LEFT_ANKLE  = 15                # halpe26 sol ayak bileği indeksi
    RIGHT_ANKLE = 16                # halpe26 sağ ayak bileği indeksi

    FRAME_W      = 640
    FRAME_H      = 480
    INFER_EVERY  = 3      # Her 3 display frame'ine 1 inference
    STREAM_FPS   = 30     # Hedef display FPS
    INFER_Q_SIZE = 1      # İnference kuyruğu — 1: her zaman en taze frame

    def __init__(self, session_id: int, source_type: str, source_value: str,
                 zone, algorithm_type: str, detector, pose_estimator,
                 xg_detector, xg_config: dict, snapshot_folder: Path,
                 det_score_thr: float = 0.35, kpt_thr: float = 0.30, app=None):
        self.session_id      = session_id
        self.source_type     = source_type
        self.source_value    = source_value
        self.zone            = np.array(zone, dtype=np.int32) if zone else None
        self.algorithm_type  = algorithm_type
        self.detector        = detector
        self.pose_estimator  = pose_estimator
        self.xg_detector     = xg_detector
        self.xg_config       = xg_config or {}
        self.snapshot_folder = snapshot_folder
        self.det_score_thr   = det_score_thr
        self.kpt_thr         = kpt_thr
        self._app            = app

        # Durum
        self._running      = False
        self._lock         = threading.Lock()
        self._latest_frame = None          # JPEG bytes — stream endpoint okur
        self._cap          = None
        self._frame_count  = 0

        # ── İnference thread için paylaşılan durum ──────────────────────────
        self._infer_q: queue.Queue = queue.Queue(maxsize=self.INFER_Q_SIZE)
        self._result_lock          = threading.Lock()
        # Son inference sonucu — display thread'i bu cache'den okur
        self._cached: dict = {
            'annotated': None,   # BGR ndarray — son annotate edilmiş frame
            'violated':  False,
            'count':     0,
        }
        self._infer_thread: Optional[threading.Thread] = None

    # ─────────────────────────────────────────────────────────────────────────
    def start(self):
        self._running = True
        # 1) İnference daemon thread (gerçek OS thread — CPU'yu bloke edebilir)
        self._infer_thread = threading.Thread(
            target=self._infer_loop, daemon=True, name=f'infer-{self.session_id}'
        )
        self._infer_thread.start()
        # 2) Display + socketio greenlet (sadece frame okuma / encode / emit)
        socketio.start_background_task(self._loop)

    def stop(self):
        self._running = False
        # Kuyruğu temizle + sentinel gönder ki thread uyanıp çıksın
        try:
            while not self._infer_q.empty():
                self._infer_q.get_nowait()
        except Exception:
            pass
        try:
            self._infer_q.put_nowait(None)   # sentinel
        except Exception:
            pass
        if self._cap:
            self._cap.release()
            self._cap = None

    @property
    def latest_frame(self):
        with self._lock:
            return self._latest_frame

    # ─────────────────────────────────────────────────────────────────────────
    def _open_capture(self):
        if self.source_type == 'file':
            cap = cv2.VideoCapture(str(self.source_value))
        elif self.source_type == 'rtsp':
            cap = cv2.VideoCapture(self.source_value, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        elif self.source_type == 'webcam':
            cap = cv2.VideoCapture(int(self.source_value or 0))
        else:
            return None
        return cap if cap.isOpened() else None

    # ══════════════════════════════════════════════════════════════════════════
    # INFERENCE THREAD — ağır CPU işi burada, greenlet'i bloke etmez
    # ══════════════════════════════════════════════════════════════════════════
    def _infer_loop(self):
        """Daemon thread: kuyruktaki ham frame'leri inference eder."""
        with self._app.app_context():
            while self._running:
                try:
                    item = self._infer_q.get(timeout=1.0)
                except queue.Empty:
                    continue

                if item is None:          # stop() sentinel
                    break

                small = item

                try:
                    if self.algorithm_type == 'zone_detector':
                        annotated, violated, count = self._run_zone(small)
                    else:
                        annotated, violated, count = self._run_xg(small)
                except Exception as e:
                    logger.error(f'[Infer] Hata: {e}', exc_info=True)
                    annotated, violated, count = small.copy(), False, 0

                # NOT: Zone overlay arka planda çizilmez.
                # Frontend canvas.js zaten poligonu ekran üzerinde doğru çizer.
                # Burada çizmek çift/kaymış poligona yol açar.

                with self._result_lock:
                    self._cached['annotated'] = annotated
                    self._cached['violated']  = violated
                    self._cached['count']     = count

    # ══════════════════════════════════════════════════════════════════════════
    # DISPLAY GREENLET — sadece frame okuma, overlay ve encode
    # ══════════════════════════════════════════════════════════════════════════
    def _loop(self):
        from app.models.violation import ViolationEvent
        _sleep = _get_sleep()
        frame_interval = 1.0 / self.STREAM_FPS

        with self._app.app_context():
            self._cap = self._open_capture()
            if self._cap is None:
                socketio.emit('session_error',
                              {'session_id': self.session_id,
                               'msg': 'Video kaynağı açılamadı'},
                              room=f'session_{self.session_id}',
                              namespace='/')
                logger.error(f'[Stream] Session {self.session_id}: Video açılamadı')
                return

            # XGDetector sıfırlama
            if self.algorithm_type == 'xg_detector' and self.xg_detector:
                fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
                if hasattr(self.xg_detector, 'reset'):
                    self.xg_detector.reset(fps=fps)
                if hasattr(self.xg_detector, 'set_zone'):
                    self.xg_detector.set_zone(
                        self.zone.tolist() if self.zone is not None else None
                    )

            last_violation  = False
            reconnect_count = 0
            emit_count      = 0

            while self._running:
                t0 = time.time()

                ret, frame = self._cap.read()
                if not ret:
                    if self.source_type == 'file':
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        _sleep(0.05)
                        continue
                    elif self.source_type == 'rtsp' and reconnect_count < 5:
                        reconnect_count += 1
                        _sleep(2.0)
                        self._cap.release()
                        self._cap = self._open_capture()
                        if self._cap is None:
                            break
                        continue
                    else:
                        break

                reconnect_count = 0
                self._frame_count += 1
                small = cv2.resize(frame, (self.FRAME_W, self.FRAME_H))

                # ── Her INFER_EVERY frame'de 1 inference gönder ──────────────
                if self._frame_count % self.INFER_EVERY == 0:
                    try:
                        # Bloke etmeden kuyruğa koy; doluysa atla (en taze frame)
                        try:
                            self._infer_q.get_nowait()   # eskileri temizle
                        except queue.Empty:
                            pass
                        self._infer_q.put_nowait(small.copy())
                    except queue.Full:
                        pass

                # ── Mevcut cache'i al ve display frame'i hazırla ─────────────
                with self._result_lock:
                    cached_ann  = self._cached.get('annotated')
                    violated    = self._cached.get('violated', False)
                    count       = self._cached.get('count', 0)

                if cached_ann is not None and cached_ann.shape == small.shape:
                    # İnference sonucu mevcut — annotated frame'i göster
                    display = cached_ann
                else:
                    # Henüz inference yok — ham frame (zone çizimi frontend canvas'ta)
                    display = small.copy()

                # JPEG encode
                _, buf = cv2.imencode('.jpg', display,
                                      [cv2.IMWRITE_JPEG_QUALITY, 82])
                with self._lock:
                    self._latest_frame = buf.tobytes()

                # ── Violation kayıt + emit (her değişimde) ────────────────────
                if violated and not last_violation:
                    snap  = self._save_snapshot(display)
                    event = ViolationEvent(
                        session_id    = self.session_id,
                        person_count  = count,
                        in_violation  = True,
                        snapshot_path = snap,
                    )
                    db.session.add(event)
                    db.session.commit()
                    socketio.emit('violation', {
                        'session_id':   self.session_id,
                        'person_count': count,
                        'snapshot':     snap,
                        'timestamp':    datetime.utcnow().isoformat(),
                        'algorithm':    self.algorithm_type,
                    }, room=f'session_{self.session_id}', namespace='/')

                last_violation = violated

                # Stats emiti her 3 display frame'de 1 (gereksiz emit azaltılır)
                emit_count += 1
                if emit_count % 3 == 0:
                    socketio.emit('stats', {
                        'session_id': self.session_id,
                        'count':      count,
                        'violated':   violated,
                        'algorithm':  self.algorithm_type,
                    }, room=f'session_{self.session_id}', namespace='/')

                # Hedef FPS'e göre uyku
                elapsed = time.time() - t0
                sleep_t = max(0.0, frame_interval - elapsed)
                _sleep(sleep_t)

            socketio.emit('session_ended', {'session_id': self.session_id},
                          room=f'session_{self.session_id}', namespace='/')

    # ══════════════════════════════════════════════════════════════════════════
    # INFERENCE YARDIMCILARı
    # ══════════════════════════════════════════════════════════════════════════

    def _run_zone(self, small: np.ndarray):
        """
        Alan İhlal Algoritması — YOLO detection → affine crop → RTMPose.
        Çalışma yeri: daemon inference thread.
        """
        violated     = False
        person_count = 0

        if self.detector is None or self.pose_estimator is None:
            return small, violated, person_count

        try:
            # Detection
            boxes, scores, _ = self.detector.process_image(
                small, conf_thres=self.det_score_thr)

            if boxes is None or len(boxes) == 0:
                return small, violated, person_count

            person_count = len(boxes)

            # Affine crop → pose
            image_rgb       = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            crops, matrices = self._prepare_crops(image_rgb, boxes)
            kpts_crop, kpt_scores = self.pose_estimator.process_image(crops)
            kpts = self._affine_inverse(kpts_crop, matrices)

            # Zone testi
            labels = []
            for i in range(len(boxes)):
                v = self._foot_in_zone(kpts[i], kpt_scores[i])
                labels.append(1 if v else 0)
                if v:
                    violated = True

            labels_arr = np.array(labels, dtype=np.int32)

            # Çizim (orijinal BGR frame üzerine)
            annotated = self.detector.draw(small, boxes, scores, labels_arr)
            annotated = self.pose_estimator.draw(annotated, kpts, kpt_scores)

        except Exception as e:
            logger.error(f'[ZoneDetector] Hata: {e}', exc_info=True)
            annotated = small.copy()

        return annotated, violated, person_count

    def _run_xg(self, small: np.ndarray):
        """İstenmeyen Obje Algoritması. Çalışma yeri: daemon inference thread."""
        if self.xg_detector is None or not self.xg_detector.is_ready():
            return small, False, 0
        try:
            if hasattr(self.xg_detector, 'set_zone'):
                self.xg_detector.set_zone(
                    self.zone.tolist() if self.zone is not None else None
                )
            annotated, violated, count = self.xg_detector.process_frame(small)
            return annotated, violated, count
        except Exception as e:
            logger.error(f'[XGDetector] Hata: {e}', exc_info=True)
            return small, False, 0

    # ── Zone overlay ──────────────────────────────────────────────────────────
    def _draw_zone(self, frame: np.ndarray, violated: bool) -> np.ndarray:
        """Zone polygon'unu frame üzerine çiz (BGR)."""
        if self.zone is None:
            return frame
        overlay = frame.copy()
        # BGR renk: mavi ton (ihlal → kırmızı, normal → mavi)
        color_fill   = (30, 30, 180)  if violated else (200, 80,  0)
        color_border = (0,  0,  220)  if violated else (200, 120, 20)
        cv2.fillPoly(overlay, [self.zone], color_fill)
        cv2.addWeighted(overlay, 0.20, frame, 0.80, 0, frame)
        cv2.polylines(frame, [self.zone], True, color_border, 2, cv2.LINE_AA)
        return frame

    # ── Affine yardımcılar ────────────────────────────────────────────────────
    def _foot_in_zone(self, kpts, kpt_scores) -> bool:
        if self.zone is None:
            return False
        for idx in (self.LEFT_ANKLE, self.RIGHT_ANKLE):
            if idx < len(kpt_scores) and kpt_scores[idx] >= self.kpt_thr:
                pt = (float(kpts[idx, 0]), float(kpts[idx, 1]))
                if cv2.pointPolygonTest(self.zone, pt, False) >= 0:
                    return True
        return False

    @staticmethod
    def _xyxy_to_cs(box, input_size, padding=1.25):
        x1, y1, x2, y2 = box[:4]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        w, h   = (x2 - x1) * padding, (y2 - y1) * padding
        aspect = input_size[0] / input_size[1]
        if w > h * aspect:
            h = w / aspect
        else:
            w = h * aspect
        return (
            np.array([cx, cy], dtype=np.float32),
            np.array([w,  h],  dtype=np.float32),
        )

    @staticmethod
    def _get_affine_matrix(center, scale, output_size):
        W, H   = output_size
        sw, sh = scale
        src = np.array([
            [center[0],            center[1]           ],
            [center[0] + sw * 0.5, center[1]           ],
            [center[0],            center[1] + sh * 0.5],
        ], dtype=np.float32)
        dst = np.array([
            [W * 0.5, H * 0.5],
            [W,       H * 0.5],
            [W * 0.5, H      ],
        ], dtype=np.float32)
        return cv2.getAffineTransform(src, dst)

    @staticmethod
    def _affine_inverse(kpts_crop, matrices):
        N, K, _ = kpts_crop.shape
        result  = np.zeros_like(kpts_crop)
        for i, M in enumerate(matrices):
            M_inv     = cv2.invertAffineTransform(M)
            pts_h     = np.concatenate(
                [kpts_crop[i], np.ones((K, 1), dtype=np.float32)], axis=1
            )
            result[i] = (M_inv @ pts_h.T).T[:, :2]
        return result

    def _prepare_crops(self, image_rgb, boxes):
        W, H     = self._POSE_INPUT_SIZE
        N        = len(boxes)
        crops    = np.zeros((N, H, W, 3), dtype=np.uint8)
        matrices = []
        for i, box in enumerate(boxes):
            center, scale = self._xyxy_to_cs(box, self._POSE_INPUT_SIZE)
            M             = self._get_affine_matrix(center, scale, (W, H))
            crop          = cv2.warpAffine(image_rgb, M, (W, H),
                                           flags=cv2.INTER_LINEAR)
            crops[i]      = crop
            matrices.append(M)
        return crops, matrices

    def _save_snapshot(self, frame):
        try:
            fname = f'snap_{self.session_id}_{int(time.time()*1000)}.jpg'
            path  = self.snapshot_folder / fname
            cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return fname
        except Exception:
            return None


# ═════════════════════════════════════════════════════════════════════════════
class StreamManager:
    def __init__(self):
        self._sessions: Dict[int, StreamSession] = {}
        self._lock = threading.Lock()

    def start_session(self, session_id, source_type, source_value,
                      zone, algorithm_type, detector, pose_estimator,
                      xg_detector, xg_config, snapshot_folder,
                      det_score_thr=0.35, kpt_thr=0.30):
        from flask import current_app
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            s = StreamSession(
                session_id, source_type, source_value, zone,
                algorithm_type, detector, pose_estimator,
                xg_detector, xg_config or {}, snapshot_folder,
                det_score_thr, kpt_thr,
                app=current_app._get_current_object(),
            )
            s.start()
            self._sessions[session_id] = s
            return s

    def stop_session(self, session_id):
        with self._lock:
            s = self._sessions.pop(session_id, None)
        if s:
            s.stop()

    def get_session(self, session_id):
        return self._sessions.get(session_id)

    def active_ids(self):
        return list(self._sessions.keys())

    def active_count(self):
        return len(self._sessions)


stream_manager = StreamManager()
