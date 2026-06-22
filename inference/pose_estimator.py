"""
pose_estimator.py

Değişiklikler:
    - preprocess artık hazır crop'lar alır (N,H,W,3) — box bağımlılığı kaldırıldı
    - postprocess sadece SimCC decode yapar, affine inverse ZVD'ye taşındı
    - process_image / inference crop batch alır, crop-space kpts döner
    - _xyxy_to_cs / _get_affine_matrix / _affine_inverse → zone_violation_detector.py

Public metodlar (BaseModel sözleşmesi):
    preprocess(crops)           → normalize + transpose
    postprocess(raw_output)     → SimCC decode, crop koordinatlarında kpts
    inference(crops)            → tam pose pipeline'ı
    process_image(crops)        → pose pipeline'ı
    draw(canvas, kpts, scores)  → iskelet görselleştirme, canvas döner
    _onnx_inf                   → ONNX inference
    _openvino_inf               → OpenVINO inference
    _trt_inf                    → NotImplementedError
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union

import cv2
import numpy as np

from .base_model import BaseModel, EngineType

# ---------------------------------------------------------------------------
_POSE_MEAN = np.array([123.675, 116.28,  103.53], dtype=np.float32)
_POSE_STD  = np.array([ 58.395,  57.12,   57.375], dtype=np.float32)

_SKELETON_PAIRS = [
    (0, 1),  (0, 2),  (1, 3),  (2, 4),
    (5, 6),  (5, 7),  (7, 9),  (6, 8),  (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13),(13, 15),(12, 14),(14, 16),
    (15, 17),(16, 18),
    (17, 19),(18, 20),
    (19, 21),(20, 22),
    (21, 23),(22, 24),
    (23, 25),
]
_SKELETON_COLORS = [
    (255,   0,   0), (255,  85,   0), (255, 170,   0), (255, 255,   0),
    (170, 255,   0), ( 85, 255,   0), (  0, 255,   0), (  0, 255,  85),
    (  0, 255, 170), (  0, 255, 255), (  0, 170, 255), (  0,  85, 255),
    (  0,   0, 255), ( 85,   0, 255), (170,   0, 255), (255,   0, 255),
    (255,   0, 170), (255,   0,  85), (255,   0,   0), (255,  85,   0),
    (255, 170,   0), (255, 255,   0), (  0, 255,   0), (  0,   0, 255),
    ( 85,   0, 255), (170,   0, 255),
]


class PoseEstimator(BaseModel):
    """
    RTMPose-t tabanlı pose tahmincisi. halpe26 formatında 26 keypoint.

    Parametreler
    ------------
    model_path   : RTMPose .onnx veya OpenVINO .xml
    input_size   : Model giriş boyutu (W, H)
    kpt_thr      : Keypoint görünürlük eşiği
    engine       : 'openvino' | 'onnxruntime'
    use_logging  : True → loglama aktif
    log_file     : None → konsol, str → dosyaya yaz

    Dönüş formatı — process_image / inference:
        kpts_crop  : (N, 26, 2) float32 — CROP piksel koordinatları
        kpt_scores : (N, 26)    float32 — keypoint güven skorları

    NOT: Orijinal koordinata dönüşüm (_affine_inverse) ZoneViolationDetector'da yapılır.
    """

    NUM_KPT      = 26
    _SIMCC_SPLIT = 2.0

    def __init__(
        self,
        model_path:  Union[str, Path],
        input_size:  Tuple[int, int] = (192, 256),
        kpt_thr:     float = 0.30,
        engine:      str   = 'openvino',
        use_logging: bool  = True,
        log_file:    Optional[str] = None,
    ) -> None:
        super().__init__()

        self.model_path  = Path(model_path)
        self.logger      = self._create_logger(__name__, log_file) if use_logging else None
        self.kpt_thr     = kpt_thr
        self._input_size = input_size

        self.model, self.engine_type = self.set_model(self.model_path, engine)

        if self.logger:
            self.logger.info(f'[PoseEstimator] {model_path}  engine={engine}')

    # =======================================================================
    # BaseModel sözleşmesi
    # =======================================================================

    def preprocess(
        self,
        crops: np.ndarray,
    ) -> Optional[np.ndarray]:
        """
        Crop batch normalize + transpose.

        Alır  : crops (N, H, W, 3) RGB uint8/float32 — ZVD tarafından warpAffine ile hazırlanmış
        Döner : batch (N, 3, H, W) float32 normalize
                Hata → None
        """
        try:
            N      = len(crops)
            W, H   = self._input_size
            batch  = np.zeros((N, 3, H, W), dtype=np.float32)
            for i, crop in enumerate(crops):
                normalized = (crop.astype(np.float32) - _POSE_MEAN) / _POSE_STD
                batch[i]   = normalized.transpose(2, 0, 1)
            return batch
        except Exception as e:
            if self.logger:
                self.logger.error(f'preprocess hatası: {e}')
            return None

    def postprocess(
        self,
        raw_output: Union[tuple, np.ndarray],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        SimCC veya direkt format → crop koordinatlarında kpts.

        Döner : (kpts_crop (N,26,2) float32, kpt_scores (N,26) float32)
                Hata → sıfır dolu diziler

        NOT: Affine inverse (crop → orijinal piksel) ZVD tarafından uygulanır.
        """
        try:
            if isinstance(raw_output, np.ndarray):
                return raw_output[..., :2], raw_output[..., 2]

            simcc_x, simcc_y = raw_output[0], raw_output[1]
            locs_x = np.argmax(simcc_x, axis=2).astype(np.float32)
            locs_y = np.argmax(simcc_y, axis=2).astype(np.float32)
            kpts_crop = np.stack(
                [locs_x / self._SIMCC_SPLIT, locs_y / self._SIMCC_SPLIT], axis=2
            )
            scores = (np.amax(simcc_x, axis=2) + np.amax(simcc_y, axis=2)) / 2.0
            return kpts_crop, scores

        except Exception as e:
            if self.logger:
                self.logger.error(f'postprocess hatası: {e}')
            return (
                np.zeros((0, self.NUM_KPT, 2), dtype=np.float32),
                np.zeros((0, self.NUM_KPT),    dtype=np.float32),
            )

    def inference(
        self,
        crops: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Tek çağrıda pose pipeline'ı.

        Alır  : crops (N, H, W, 3) RGB — ZVD tarafından hazırlanmış
        Döner : (kpts_crop (N,26,2), kpt_scores (N,26)) — crop koordinatları
        """
        return self.process_image(crops)

    def process_image(
        self,
        crops: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Crop batch üzerinde pose pipeline'ı.

        Alır  : crops (N, H, W, 3) RGB — ZVD tarafından hazırlanmış
        Döner : (kpts_crop (N,26,2) float32, kpt_scores (N,26) float32) — crop koordinatları
                Hata → sıfır dolu diziler
        """
        try:
            N     = len(crops)
            batch = self.preprocess(crops)
            if batch is None:
                return (
                    np.zeros((N, self.NUM_KPT, 2), dtype=np.float32),
                    np.zeros((N, self.NUM_KPT),    dtype=np.float32),
                )

            if self.engine_type == EngineType.ONNX:
                raw = self._onnx_inf(batch)
            elif self.engine_type == EngineType.OPENVINO:
                raw = self._openvino_inf(batch)
            else:
                return (
                    np.zeros((N, self.NUM_KPT, 2), dtype=np.float32),
                    np.zeros((N, self.NUM_KPT),    dtype=np.float32),
                )

            if raw is None:
                return (
                    np.zeros((N, self.NUM_KPT, 2), dtype=np.float32),
                    np.zeros((N, self.NUM_KPT),    dtype=np.float32),
                )

            return self.postprocess(raw)

        except Exception as e:
            if self.logger:
                self.logger.error(f'process_image hatası: {e}')
            return (
                np.zeros((N, self.NUM_KPT, 2), dtype=np.float32),
                np.zeros((N, self.NUM_KPT),    dtype=np.float32),
            )

    def draw(
        self,
        canvas:     np.ndarray,
        kpts:       np.ndarray,
        kpt_scores: np.ndarray,
    ) -> np.ndarray:
        """
        Renkli iskelet + keypoint noktaları çizer.

        Alır  : canvas (BGR ndarray), kpts (N,26,2), kpt_scores (N,26)
        Döner : annotated BGR ndarray (kopya)
        """
        try:
            canvas = canvas.copy()
            for kpts_p, scores_p in zip(kpts, kpt_scores):
                for pair_idx, (a, b) in enumerate(_SKELETON_PAIRS):
                    if scores_p[a] >= self.kpt_thr and scores_p[b] >= self.kpt_thr:
                        cv2.line(
                            canvas,
                            (int(kpts_p[a, 0]), int(kpts_p[a, 1])),
                            (int(kpts_p[b, 0]), int(kpts_p[b, 1])),
                            _SKELETON_COLORS[pair_idx % len(_SKELETON_COLORS)],
                            2, lineType=cv2.LINE_AA,
                        )
                for k in range(self.NUM_KPT):
                    if scores_p[k] >= self.kpt_thr:
                        cv2.circle(
                            canvas,
                            (int(kpts_p[k, 0]), int(kpts_p[k, 1])),
                            3, (255, 255, 255), -1, lineType=cv2.LINE_AA,
                        )
            return canvas

        except Exception as e:
            if self.logger:
                self.logger.error(f'draw hatası: {e}')
            return canvas

    def _onnx_inf(
        self, batch: np.ndarray
    ) -> Optional[Union[tuple, np.ndarray]]:
        try:
            try:
                outputs = self.model.run(
                    None, {self.model.get_inputs()[0].name: batch}
                )
            except Exception:
                outputs = self._pose_sequential_onnx(batch)
            return (outputs[0], outputs[1]) if len(outputs) == 2 else outputs[0]
        except Exception as e:
            if self.logger:
                self.logger.error(f'ONNX inference hatası: {e}')
            return None

    def _openvino_inf(
        self, batch: np.ndarray
    ) -> Optional[Union[tuple, np.ndarray]]:
        try:
            try:
                result = self.model(batch)
            except Exception:
                result = self._pose_sequential_ov(batch)
            if len(self.model.outputs) >= 2:
                return (
                    result[self.model.output(0)],
                    result[self.model.output(1)],
                )
            return result[self.model.output(0)]
        except Exception as e:
            if self.logger:
                self.logger.error(f'OpenVINO inference hatası: {e}')
            return None

    def _trt_inf(self, preprocessed_image: np.ndarray) -> None:
        raise NotImplementedError('TensorRT henüz desteklenmiyor.')

    # =======================================================================
    # İç yardımcılar
    # =======================================================================

    def _pose_sequential_onnx(self, batch: np.ndarray) -> list:
        results = [
            self.model.run(
                None, {self.model.get_inputs()[0].name: batch[i:i + 1]}
            )
            for i in range(len(batch))
        ]
        return [
            np.concatenate([r[j] for r in results], axis=0)
            for j in range(len(results[0]))
        ]

    def _pose_sequential_ov(self, batch: np.ndarray) -> dict:
        all_out = [self.model(batch[i:i + 1]) for i in range(len(batch))]
        return {
            self.model.output(j): np.concatenate(
                [o[self.model.output(j)] for o in all_out], axis=0
            )
            for j in range(len(all_out[0]))
        }
