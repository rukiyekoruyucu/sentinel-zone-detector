"""
zone_violation_detector.py 
Detector ve PoseEstimator'ı pipeline olarak yönetir.

Değişiklikler:
    - find_video / pick_zone / draw_zone → main.py'e taşındı
    - _xyxy_to_cs / _get_affine_matrix / _affine_inverse pose_estimator'dan buraya taşındı
    - _prepare_crops: detection box'larını affine crop'a dönüştürür, ZVD sorumluluğu
    - draw() bug düzeltildi: canvas = self._pose.draw(...) return değeri yakalanıyor

Public metodlar (BaseModel sözleşmesi):
    preprocess(image)          → detection preprocess'e yönlendirir
    postprocess(...)           → detection postprocess'e yönlendirir
    inference(input_data)      → tam pipeline
    process_image(image)       → det + crop + pose + zone testi
    draw(image, ...)           → bbox + iskelet
    _onnx_inf                  → detection ONNX inference
    _openvino_inf              → detection OpenVINO inference
    _trt_inf                   → NotImplementedError

İç yardımcılar:
    _prepare_crops             → boxes → warpAffine crop batch + matrices
    _xyxy_to_cs                → bbox → center/scale (dinamik aspect ratio)
    _get_affine_matrix         → affine matris üretimi
    _affine_inverse            → crop → orijinal koordinat
    _foot_in_zone              → ayak ucu zone testi
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union

import cv2
import numpy as np

from .base_model import BaseModel, EngineType
from .detector import Detector
from .pose_estimator import PoseEstimator


class ZoneViolationDetector(BaseModel):
    """
    Detector ve PoseEstimator'ı dahili olarak yönetir.

    Parametreler
    ------------
    det_model_path  : YOLOv11 .onnx veya OpenVINO .xml
    pose_model_path : RTMPose-t .onnx veya OpenVINO .xml
    zone            : Yasak bölge poligonu (M, 2) int32 — orijinal piksel
    det_input_size  : YOLO model giriş boyutu (W, H)
    pose_input_size : RTMPose model giriş boyutu (W, H)
    score_thr       : Kişi tespiti güven eşiği
    nms_thr         : NMS IoU eşiği
    kpt_thr         : Keypoint görünürlük eşiği
    engine          : 'openvino' | 'onnxruntime'
    use_logging     : True → loglama aktif
    log_file        : None → konsol, str → dosyaya yaz

    Dönüş formatı — process_image / inference:
        in_zone     : bool            — yasak bölgede ayak var mı
        kpts        : (N,26,2) f32    — orijinal piksel koordinatları
        foot_tips   : (N,2,2)  f32    — [sol_ayak, sağ_ayak] koordinatları
        boxes       : (N,4)    f32    — xyxy bbox
        kpt_scores  : (N,26)   f32    — keypoint güven skorları
        labels      : (N,)     int32  — 0: temiz, 1: ihlal
    """

    LEFT_ANKLE_IDX  = 15   # halpe26: sol ayak bileği (düzeltildi: eskiden 24 — COCO-17 dışı)
    RIGHT_ANKLE_IDX = 16   # halpe26: sağ ayak bileği (düzeltildi: eskiden 25 — COCO-17 dışı)

    def __init__(
        self,
        det_model_path:  Union[str, Path],
        pose_model_path: Union[str, Path],
        zone:            np.ndarray,
        det_input_size:  Tuple[int, int] = (640, 640),
        pose_input_size: Tuple[int, int] = (192, 256),
        score_thr:       float = 0.35,
        nms_thr:         float = 0.45,
        kpt_thr:         float = 0.30,
        engine:          str   = 'openvino',
        use_logging:     bool  = True,
        log_file:        Optional[str] = None,
    ) -> None:
        super().__init__()

        self.logger    = self._create_logger(__name__, log_file) if use_logging else None
        self.score_thr = score_thr
        self.kpt_thr   = kpt_thr

        zone_arr = np.asarray(zone, dtype=np.int32)
        if zone_arr.ndim != 2 or zone_arr.shape[1] != 2:
            raise ValueError('zone (M, 2) int32 formatında olmalı.')
        self.zone = zone_arr

        self._detector = Detector(
            model_path  = det_model_path,
            input_size  = det_input_size,
            score_thr   = score_thr,
            nms_thr     = nms_thr,
            engine      = engine,
            use_logging = use_logging,
            log_file    = log_file,
        )
        self._pose = PoseEstimator(
            model_path  = pose_model_path,
            input_size  = pose_input_size,
            kpt_thr     = kpt_thr,
            engine      = engine,
            use_logging = use_logging,
            log_file    = log_file,
        )

        if self.logger:
            self.logger.info(
                f'[ZVD] Det={det_model_path}  Pose={pose_model_path}  engine={engine}'
            )

    # ------------------------------------------------------------------
    # BaseModel sözleşmesi — Detection'a yönlendirir
    # ------------------------------------------------------------------

    def preprocess(self, image: np.ndarray, **kwargs):
        return self._detector.preprocess(image, **kwargs)

    def postprocess(self, prediction: np.ndarray, *args, **kwargs):
        return self._detector.postprocess(prediction, *args, **kwargs)

    def inference(
        self,
        input_data: Union[np.ndarray, str, Path],
        conf_thres: float = 0.25,
    ) -> tuple:
        """
        Tek görüntü veya dosya yolu üzerinde tam pipeline.

        Alır  : BGR ndarray  VEYA  görüntü dosya yolu
        Döner : (in_zone, kpts, foot_tips, boxes, kpt_scores, labels)
                Hata → _empty_result()
        """
        try:
            if isinstance(input_data, (str, Path)):
                img = cv2.imread(str(input_data))
                if img is None:
                    raise FileNotFoundError(f'Görüntü okunamadı: {input_data}')
            elif isinstance(input_data, np.ndarray):
                img = input_data
            else:
                raise TypeError(f'Desteklenmeyen tip: {type(input_data)}')

            return self.process_image(img, conf_thres=conf_thres)

        except Exception as e:
            if self.logger:
                self.logger.error(f'inference hatası: {e}')
            return self._empty_result()

    def process_image(
        self,
        image:      np.ndarray,
        conf_thres: float = 0.25,
    ) -> tuple:
        """
        Detection → Crop → Pose → Affine Inverse → Zone testi tam pipeline'ı.

        Alır  : BGR ndarray (orijinal çözünürlük)
        Döner : (
            in_zone:    bool,
            kpts:       (N,26,2) float32  — orijinal piksel,
            foot_tips:  (N,2,2)  float32  — [sol_ayak, sağ_ayak],
            boxes:      (N,4)    float32  — xyxy bbox,
            kpt_scores: (N,26)   float32  — keypoint güven skorları,
            labels:     (N,)     int32    — 0: temiz, 1: ihlal
        )
        Hata / tespit yok → _empty_result()
        """
        try:
            # 1. Detection — Detector BGR→RGB dönüşümünü kendi içinde yapar
            boxes, _, _ = self._detector.process_image(image, conf_thres=conf_thres)

            if boxes is None or len(boxes) == 0:
                return self._empty_result()

            # 2. Detection box'larını affine crop'a dönüştür (ZVD sorumluluğu)
            image_rgb        = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            crops, matrices  = self._prepare_crops(image_rgb, boxes)

            # 3. Pose — crop koordinatlarında kpts döner
            kpts_crop, kpt_scores = self._pose.process_image(crops)

            # 4. Affine inverse → orijinal piksel koordinatları (ZVD sorumluluğu)
            kpts = self._affine_inverse(kpts_crop, matrices)

            # 5. Ayak bileği keypoint'leri — (N, 2, 2): [sol_ayak_bileği, sağ_ayak_bileği]
            foot_tips = kpts[:, [self.LEFT_ANKLE_IDX, self.RIGHT_ANKLE_IDX], :]

            # 6. Zone testi
            N       = len(boxes)
            labels  = np.zeros(N, dtype=np.int32)
            in_zone = False
            for i in range(N):
                if self._foot_in_zone(kpts[i], kpt_scores[i]):
                    labels[i] = 1
                    in_zone   = True

            return (in_zone, kpts, foot_tips, boxes, kpt_scores, labels)

        except Exception as e:
            if self.logger:
                self.logger.error(f'process_image hatası: {e}')
            return self._empty_result()

    def draw(
        self,
        image:      np.ndarray,
        boxes:      np.ndarray,
        kpt_scores: np.ndarray,
        labels:     np.ndarray,
        kpts:       Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Bbox + iskelet çizer. Orijinal çözünürlükte, kopya üzerinde.

        Alır  : BGR ndarray + process_image çıktıları
        Döner : annotated BGR ndarray
        """
        try:
            canvas = self._detector.draw(image, boxes, kpt_scores, labels)
            if kpts is not None and len(boxes) > 0:
                canvas = self._pose.draw(canvas, kpts, kpt_scores)  # FIX: return yakalanıyor
            return canvas

        except Exception as e:
            if self.logger:
                self.logger.error(f'draw hatası: {e}')
            return image

    def _onnx_inf(self, preprocessed_image: np.ndarray) -> Optional[np.ndarray]:
        return self._detector._onnx_inf(preprocessed_image)

    def _openvino_inf(self, preprocessed_image: np.ndarray) -> Optional[np.ndarray]:
        return self._detector._openvino_inf(preprocessed_image)

    def _trt_inf(self, preprocessed_image: np.ndarray) -> None:
        raise NotImplementedError('TensorRT henüz desteklenmiyor.')

    # =======================================================================
    # İç yardımcılar
    # =======================================================================

    def _prepare_crops(
        self,
        image_rgb: np.ndarray,
        boxes:     np.ndarray,
    ) -> Tuple[np.ndarray, list]:
        """
        Detection box'larını affine crop batch'e dönüştürür.

        Alır  : RGB ndarray (orijinal çözünürlük), boxes (N,4) xyxy
        Döner : (crops (N,H,W,3) uint8, matrices list) — pose'a hazır
        """
        N        = len(boxes)
        W, H     = self._pose._input_size
        crops    = np.zeros((N, H, W, 3), dtype=np.uint8)
        matrices = []

        for i, box in enumerate(boxes):
            center, scale = self._xyxy_to_cs(box, self._pose._input_size)
            M             = self._get_affine_matrix(center, scale, (W, H))
            crop          = cv2.warpAffine(image_rgb, M, (W, H), flags=cv2.INTER_LINEAR)
            crops[i]      = crop
            matrices.append(M)

        return crops, matrices

    @staticmethod
    def _xyxy_to_cs(
        box:        np.ndarray,
        input_size: Tuple[int, int],
        padding:    float = 1.25,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Bbox'u center/scale'e dönüştürür.

        Alır  : box (4,) xyxy, input_size (W, H), padding
        Döner : (center (2,), scale (2,))

        NOT: aspect ratio input_size'dan dinamik hesaplanır — hardcode yok.
        """
        x1, y1, x2, y2 = box[:4]
        cx, cy  = (x1 + x2) / 2, (y1 + y2) / 2
        w, h    = (x2 - x1) * padding, (y2 - y1) * padding
        aspect  = input_size[0] / input_size[1]   # W / H — dinamik
        if w > h * aspect:
            h = w / aspect
        else:
            w = h * aspect
        return (
            np.array([cx, cy], dtype=np.float32),
            np.array([w,  h],  dtype=np.float32),
        )

    @staticmethod
    def _get_affine_matrix(
        center:      np.ndarray,
        scale:       np.ndarray,
        output_size: Tuple[int, int],
    ) -> np.ndarray:
        """
        Center/scale'den affine dönüşüm matrisi üretir.

        Alır  : center (2,), scale (2,), output_size (W, H)
        Döner : M (2, 3) affine matris
        """
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
    def _affine_inverse(
        kpts_crop: np.ndarray,
        matrices:  list,
    ) -> np.ndarray:
        """
        Crop koordinatlarını orijinal piksel koordinatlarına dönüştürür.

        Alır  : kpts_crop (N,26,2) — crop-space, matrices list of (2,3)
        Döner : kpts (N,26,2) — orijinal piksel koordinatları
        """
        N, K, _ = kpts_crop.shape
        result  = np.zeros_like(kpts_crop)
        for i, M in enumerate(matrices):
            M_inv     = cv2.invertAffineTransform(M)
            pts_h     = np.concatenate(
                [kpts_crop[i], np.ones((K, 1), dtype=np.float32)], axis=1
            )
            result[i] = (M_inv @ pts_h.T).T[:, :2]
        return result

    def _foot_in_zone(self, kpts: np.ndarray, kpt_scores: np.ndarray) -> bool:
        """Sol ve sağ ayak bileği keypoint'lerinden biri zone içindeyse True döner."""
        for idx in (self.LEFT_ANKLE_IDX, self.RIGHT_ANKLE_IDX):
            if kpt_scores[idx] >= self.kpt_thr:
                if cv2.pointPolygonTest(
                    self.zone,
                    (float(kpts[idx, 0]), float(kpts[idx, 1])),
                    measureDist=False,
                ) >= 0:
                    return True
        return False

    @staticmethod
    def _empty_result() -> tuple:
        return (
            False,
            np.empty((0, 26, 2), dtype=np.float32),   # kpts
            np.empty((0, 2,  2), dtype=np.float32),   # foot_tips
            np.empty((0, 4),     dtype=np.float32),   # boxes
            np.empty((0, 26),    dtype=np.float32),   # kpt_scores
            np.empty((0,),       dtype=np.int32),     # labels
        )
