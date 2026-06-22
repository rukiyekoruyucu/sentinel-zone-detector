"""
inference/xg_detector.py — XG Detector Plugin Interface
========================================================

This file is a **stub / integration template**.

The proprietary XG Detector algorithm implementation is not included in this
repository. This stub provides the interface contract so that the rest of the
SENTINEL platform can operate correctly (with XG detection gracefully disabled
until a real implementation is provided).

────────────────────────────────────────────────────────────────────────────────
HOW TO INTEGRATE YOUR OWN XG DETECTOR
────────────────────────────────────────────────────────────────────────────────

1. Implement the three methods below:
   - ``_load()``        — load / initialize your model
   - ``process_image()``— run inference on a single BGR frame
   - ``is_ready()``     — return True when the model is loaded

2. Place any supporting modules (feature extractors, pipelines, etc.) inside
   ``inference/xg/`` and import from there.

3. Set the ``XG_MODEL`` path in your ``.env`` file (if your model needs a file).

4. Restart the server — the stream pipeline picks up XG detections automatically.

────────────────────────────────────────────────────────────────────────────────
EXPECTED OUTPUT FORMAT
────────────────────────────────────────────────────────────────────────────────

``process_image()`` must return a tuple of:

    boxes   : np.ndarray  shape (N, 4)   dtype float32  — [x1, y1, x2, y2]
    scores  : np.ndarray  shape (N,)     dtype float32  — confidence [0..1]
    classes : list[str]   length N                      — class label strings

Return empty arrays / lists when there are no detections.

────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)


class XGDetector:
    """
    XG (Foreign Object / Unattended Object) Detector interface.

    Replace the body of each method with your proprietary implementation.
    """

    def __init__(self, model_path: str | None = None, conf_thr: float = 0.45):
        self._model_path = model_path
        self._conf_thr   = conf_thr
        self._ready      = False

        try:
            self._load()
        except NotImplementedError:
            logger.warning(
                "XGDetector: _load() is not implemented — XG detection is DISABLED. "
                "See inference/xg_detector.py for integration instructions."
            )
        except Exception as exc:
            logger.error("XGDetector: failed to load model — %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Return True when the detector is loaded and ready for inference."""
        return self._ready

    def process_image(
        self,
        frame: np.ndarray,
        conf_thres: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """
        Run XG detection on a single BGR frame.

        Parameters
        ----------
        frame      : np.ndarray   H×W×3 BGR image (OpenCV format)
        conf_thres : float | None Override detection threshold (uses init value if None)

        Returns
        -------
        boxes   : np.ndarray  (N, 4) — [x1, y1, x2, y2]
        scores  : np.ndarray  (N,)
        classes : list[str]   (N,)
        """
        # ── TODO: replace this stub with your implementation ─────────────────
        # Example:
        #   results = self._model(frame)
        #   return results.boxes, results.scores, results.class_names
        # ─────────────────────────────────────────────────────────────────────

        empty_boxes   = np.empty((0, 4), dtype=np.float32)
        empty_scores  = np.empty((0,),   dtype=np.float32)
        empty_classes: list[str] = []
        return empty_boxes, empty_scores, empty_classes

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """
        Initialize and load your detection model.

        Raise NotImplementedError to signal that the detector is intentionally
        left as a stub.  Replace with actual loading logic:

            import openvino as ov
            core = ov.Core()
            self._model = core.compile_model(self._model_path, "AUTO")
            self._ready = True
        """
        raise NotImplementedError(
            "XGDetector._load() is a stub — provide your implementation."
        )
