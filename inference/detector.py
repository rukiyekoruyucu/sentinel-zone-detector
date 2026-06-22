"""
detector.py — YOLOv11 
Public metodlar (BaseModel sözleşmesi):
    preprocess(image)     → letterbox + normalize
    postprocess(...)      → NMS + koordinat dönüşümü
    inference(input_data) → tam pipeline, dosya/ndarray girdisi
    process_image(image)  → detection pipeline'ı
    draw(image, ...)      → bbox görselleştirme
    _onnx_inf             → ONNX inference
    _openvino_inf         → OpenVINO inference
    _trt_inf              → NotImplementedError
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union

import cv2
import numpy as np

from .base_model import BaseModel, EngineType


class Detector(BaseModel):
    """
    YOLOv11 tabanlı kişi dedektörü.

    Parametreler
    ------------
    model_path   : YOLOv11 .onnx veya OpenVINO .xml
    input_size   : Model giriş boyutu (W, H)
    score_thr    : Kişi tespiti güven eşiği
    nms_thr      : NMS IoU eşiği
    engine       : 'openvino' | 'onnxruntime'
    use_logging  : True → loglama aktif
    log_file     : None → konsol, str → dosyaya yaz
    """

    def __init__(
        self,
        model_path:  Union[str, Path],
        input_size:  Tuple[int, int] = (640, 640),
        score_thr:   float = 0.35,
        nms_thr:     float = 0.45,
        engine:      str   = 'openvino',
        use_logging: bool  = True,
        log_file:    Optional[str] = None,
    ) -> None:
        super().__init__()

        self.logger      = self._create_logger(__name__, log_file) if use_logging else None
        self.score_thr   = score_thr
        self.nms_thr     = nms_thr
        self._input_size = input_size

        self.model, self.engine_type = self.set_model(Path(model_path), engine)

        if self.logger:
            self.logger.info(f'[Detector] {model_path}  engine={engine}')

    # BaseModel sözleşmesi
    def preprocess(
        self,
        image:   np.ndarray,
        scaleup: bool = True,
        stride:  int  = 32,
    ) -> Tuple[Optional[np.ndarray], Optional[Tuple], Optional[Tuple]]:
        """
        Letterbox + normalize.

        Alır  : RGB ndarray
        Döner : (tensor (1,3,H,W) float32, ratio (r,r), (dw, dh))
        """
        try:
            new_shape = self._input_size
            shape     = image.shape[:2]

            r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
            if not scaleup:
                r = min(r, 1.0)

            new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
            dw = (new_shape[1] - new_unpad[0]) / 2
            dh = (new_shape[0] - new_unpad[1]) / 2

            if shape[::-1] != new_unpad:
                image = cv2.resize(image, new_unpad, interpolation=cv2.INTER_LINEAR)

            img = cv2.copyMakeBorder(
                image,
                int(round(dh - 0.1)), int(round(dh + 0.1)),
                int(round(dw - 0.1)), int(round(dw + 0.1)),
                cv2.BORDER_CONSTANT, value=(114, 114, 114),
            )
            img = np.ascontiguousarray(img.transpose(2, 0, 1)).astype(np.float32) / 255.0
            return np.expand_dims(img, 0), (r, r), (dw, dh)

        except Exception as e:
            if self.logger:
                self.logger.error(f'preprocess hatası: {e}')
            return None, None, None

    def postprocess(
        self,
        prediction: np.ndarray,
        ratio:      Tuple[float, float],
        dwdh:       Tuple[float, float],
        orig_shape: Tuple[int, int],
        conf_thres: float = 0.25,
        iou_thres:  Optional[float] = None,  # FIX: None → self.nms_thr kullan
        max_det:    int   = 300,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        NMS + koordinat dönüşümü. Yalnızca person (class 0) filtreli.

        Döner : (boxes (N,4), scores (N,), classes (N,)) — orijinal piksel

        YOLOv11 çıktısı (1, 84, 8400) formatındadır:
          - 84 = 4 (bbox: cx,cy,w,h) + 80 (COCO sınıfları)
          - Objectness skoru yoktur (YOLOX'tan farkı)
          - Önce transpose ile (1, 8400, 84) yapılır
        """
        # FIX: iou_thres verilmezse self.nms_thr devreye girer
        if iou_thres is None:
            iou_thres = self.nms_thr

        try:
            # (1, 84, 8400) → (1, 8400, 84)
            prediction = prediction.transpose(0, 2, 1)

            boxes_cxcywh = prediction[0, :, :4]   # (8400, 4)
            class_scores = prediction[0, :, 4:]   # (8400, 80) — objectness yok, doğrudan class score

            # Her öneri için en yüksek sınıf skoru ve ID
            class_ids   = np.argmax(class_scores, axis=1)          # (8400,)
            confidences = class_scores[np.arange(len(class_ids)), class_ids]  # (8400,)

            # Sadece person (class 0) + eşik filtresi — NMS'den önce eleme → hız
            mask = (class_ids == 0) & (confidences > conf_thres)
            boxes_cxcywh = boxes_cxcywh[mask]
            confidences  = confidences[mask]

            if len(boxes_cxcywh) == 0:
                return None, None, None

            # cxcywh → xyxy + padding ve ratio geri dönüşümü
            dw, dh = dwdh
            r      = ratio[0]
            boxes_xyxy = np.zeros_like(boxes_cxcywh)
            boxes_xyxy[:, 0] = (boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2 - dw) / r
            boxes_xyxy[:, 1] = (boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2 - dh) / r
            boxes_xyxy[:, 2] = (boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2 - dw) / r
            boxes_xyxy[:, 3] = (boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2 - dh) / r

            # Görüntü sınırlarına kırp
            boxes_xyxy[:, 0] = np.clip(boxes_xyxy[:, 0], 0, orig_shape[1])
            boxes_xyxy[:, 1] = np.clip(boxes_xyxy[:, 1], 0, orig_shape[0])
            boxes_xyxy[:, 2] = np.clip(boxes_xyxy[:, 2], 0, orig_shape[1])
            boxes_xyxy[:, 3] = np.clip(boxes_xyxy[:, 3], 0, orig_shape[0])

            # NMS — cv2.dnn.NMSBoxes xywh formatı bekler
            boxes_xywh = boxes_xyxy.copy()
            boxes_xywh[:, 2] = boxes_xyxy[:, 2] - boxes_xyxy[:, 0]
            boxes_xywh[:, 3] = boxes_xyxy[:, 3] - boxes_xyxy[:, 1]

            indices = cv2.dnn.NMSBoxes(
                boxes_xywh.tolist(),
                confidences.tolist(),
                conf_thres,
                iou_thres,
            )

            if len(indices) == 0:
                return None, None, None

            indices      = indices.flatten()[:max_det]
            final_boxes  = np.round(boxes_xyxy[indices]).astype(np.float32)
            final_scores = confidences[indices]
            final_classes = np.zeros(len(indices), dtype=np.float32)  # hepsi person (0)

            return final_boxes, final_scores, final_classes

        except Exception as e:
            if self.logger:
                self.logger.error(f'postprocess hatası: {e}')
            return None, None, None

    def inference(
        self,
        input_data: Union[np.ndarray, str, Path],
        conf_thres: float = 0.25,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Tek görüntü veya dosya yolu üzerinde detection pipeline'ı.

        Döner : (boxes (N,4), scores (N,), classes (N,))
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
            return None, None, None

    def process_image(
        self,
        image:      np.ndarray,
        conf_thres: float = 0.25,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        BGR ndarray üzerinde detection pipeline'ı.

        Alır  : BGR ndarray (orijinal çözünürlük)
        Döner : (boxes (N,4), scores (N,), classes (N,)) — orijinal piksel
        """
        try:
            orig_shape = image.shape[:2]
            image_rgb  = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            preprocessed, ratio, dwdh = self.preprocess(image_rgb, scaleup=True)
            if preprocessed is None:
                return None, None, None

            if self.engine_type == EngineType.ONNX:
                raw = self._onnx_inf(preprocessed)
            elif self.engine_type == EngineType.OPENVINO:
                raw = self._openvino_inf(preprocessed)
            else:
                return None, None, None

            if raw is None:
                return None, None, None

            return self.postprocess(raw, ratio, dwdh, orig_shape, conf_thres=conf_thres)

        except Exception as e:
            if self.logger:
                self.logger.error(f'process_image hatası: {e}')
            return None, None, None

    def draw(
        self,
        image:  np.ndarray,
        boxes:  np.ndarray,
        scores: np.ndarray,
        labels: np.ndarray,
    ) -> np.ndarray:
        """
        Bbox + etiket çizer.

        Alır  : BGR ndarray + detection çıktıları
        Döner : annotated BGR ndarray (kopya)
        """
        try:
            canvas = image.copy()
            if boxes is None or len(boxes) == 0:
                return canvas

            for i in range(len(boxes)):
                violated  = bool(labels[i] == 1)
                color     = (0, 0, 255) if violated else (0, 255, 0)
                thickness = 3           if violated else 1

                c1 = (int(boxes[i, 0]), int(boxes[i, 1]))
                c2 = (int(boxes[i, 2]), int(boxes[i, 3]))
                cv2.rectangle(canvas, c1, c2, color,
                              thickness=thickness, lineType=cv2.LINE_AA)

                tag    = f'ID:{i} !' if violated else f'ID:{i}'
                tf     = max(thickness - 1, 1)
                t_size = cv2.getTextSize(
                    tag, 0, fontScale=thickness / 3, thickness=tf
                )[0]
                cv2.rectangle(
                    canvas,
                    (c1[0], c1[1] - t_size[1] - 3),
                    (c1[0] + t_size[0], c1[1]),
                    color, -1, lineType=cv2.LINE_AA,
                )
                cv2.putText(
                    canvas, tag, (c1[0], c1[1] - 2),
                    0, thickness / 3, (225, 255, 255),
                    thickness=tf, lineType=cv2.LINE_AA,
                )

            return canvas

        except Exception as e:
            if self.logger:
                self.logger.error(f'draw hatası: {e}')
            return image

    def _onnx_inf(self, preprocessed_image: np.ndarray) -> Optional[np.ndarray]:
        try:
            return self.model.run(
                None, {self.model.get_inputs()[0].name: preprocessed_image}
            )[0]
        except Exception as e:
            if self.logger:
                self.logger.error(f'ONNX inference hatası: {e}')
            return None

    def _openvino_inf(self, preprocessed_image: np.ndarray) -> Optional[np.ndarray]:
        try:
            result = self.model(preprocessed_image)
            return result[self.model.output(0)]
        except Exception as e:
            if self.logger:
                self.logger.error(f'OpenVINO inference hatası: {e}')
            return None

    def _trt_inf(self, preprocessed_image: np.ndarray) -> None:
        raise NotImplementedError('TensorRT henüz desteklenmiyor.')