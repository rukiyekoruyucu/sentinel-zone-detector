<div align="center">

<h1>🎯 ZoViD</h1>
<h3>Real-Time Zone Violation Detection Platform</h3>

<p>
  <strong>Zone Detector</strong> · <strong>XG Detector</strong> · <strong>Live MJPEG Streaming</strong> · <strong>Web Dashboard</strong>
</p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![OpenVINO](https://img.shields.io/badge/OpenVINO-2024.1-0071C5?style=for-the-badge&logo=intel&logoColor=white)](https://docs.openvino.ai)
[![License](https://img.shields.io/badge/License-Proprietary-red?style=for-the-badge)](LICENSE)

</div>

---

## 🌐 Overview

**ZoViD** *(Real-Time Zone Violation Detection)* is a production-ready, web-based security intelligence platform that provides real-time video analysis across multiple camera feeds from a single dashboard.

It ships with two detection pipelines:

| Pipeline | Technology | What it detects |
|---|---|---|
| **Zone Detector** | YOLO11n + RTMPose-T (OpenVINO) | People entering forbidden zones — ankle keypoint vs. polygon intersection |
| **XG Detector** | Plugin interface (proprietary) | Foreign / unattended objects — pluggable algorithm slot |

Key characteristics:
- 🎯 **Multi-camera** — manage unlimited RTSP, IP, file, or webcam sources
- ⚡ **Low-latency streaming** — MJPEG over HTTP + SocketIO real-time statistics push
- 🖊️ **Interactive zone drawing** — drag-and-drop polygon canvas per camera
- 📊 **Reports & exports** — violation log, CSV export, snapshot gallery
- 👤 **Role-based access** — admin vs. regular user, first-registered user gets admin
- 🗃️ **SQLite / PostgreSQL** — swap database with a single env variable

---

## 📸 Screenshots

<img width="1919" height="869" alt="image" src="https://github.com/user-attachments/assets/ea7ab0b5-0ac1-4429-809e-24aefe8afffe" />
<img width="1919" height="874" alt="image" src="https://github.com/user-attachments/assets/d8150a80-34d7-4712-9fa7-d8faa0cd3e12" />
<img width="1919" height="869" alt="image" src="https://github.com/user-attachments/assets/1fa61ce1-e681-49cf-9c83-f04706bf7392" />
<img width="1919" height="870" alt="image" src="https://github.com/user-attachments/assets/55ec1eb7-7ccf-4765-b9c7-d34a66e343b6" />
<img width="1919" height="866" alt="image" src="https://github.com/user-attachments/assets/a3f3816b-4e0e-40ec-9610-f08e8fa3ffac" />
<img width="1919" height="866" alt="image" src="https://github.com/user-attachments/assets/af47e039-f497-4e2f-b6e4-83f613d726c9" />
<img width="1918" height="869" alt="image" src="https://github.com/user-attachments/assets/4ab6996d-29ea-4b1f-b924-2b3cd702f5da" />
<img width="1919" height="870" alt="image" src="https://github.com/user-attachments/assets/9b230590-6ed2-48e4-ba13-eb4a261fbb09" />
<img width="1919" height="869" alt="image" src="https://github.com/user-attachments/assets/f360031f-2fdc-4b21-b16f-bf52a6a03e40" />

| Screen | Description |
|---|---|
| **Dashboard** | Camera grid with live stream thumbnails and session status |
| **Session View** | Full-screen stream + zone polygon editor + real-time violation counter |
| **Reports** | Filterable violation table, CSV download, snapshot lightbox |
| **Admin Panel** | User management, camera registry, system health |
| **Training** | XG Detector model training trigger and progress log |


---

## 🏗️ Architecture

```
Browser  ──[HTTP/WS]──►  Flask + SocketIO (eventlet)
                               │
                    ┌──────────┴──────────┐
                    │    StreamManager     │  ← one thread per active session
                    └──────────┬──────────┘
                               │ frames
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        ZoneDetector      XGDetector       MJPEG encoder
        (YOLO11n +        (plugin)         → /stream/<id>
         RTMPose-T)
              │
              ▼
        Violation DB  ──► REST API  ──► Reports / CSV
```

**Tech Stack:**

- **Backend:** Flask 3 · Flask-SocketIO · Flask-Login · Flask-Migrate · SQLAlchemy
- **Inference:** OpenVINO 2024.1 · ONNX Runtime · OpenCV
- **Frontend:** Vanilla JS · Socket.IO client · HTML5 Canvas
- **Async:** Eventlet (green threads)
- **DB:** SQLite (default) · PostgreSQL (production)

---

## ⚡ Quick Start

### Prerequisites

- Python 3.10+
- OpenVINO 2024.1+ (for model inference)
- OpenCV (`opencv-python`)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/rukiyekoruyucu/sentinel-zone-detector.git
cd sentinel-zone-detector

# 2. Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your settings (model paths, secret key, etc.)

# 5. Initialize the database
flask db upgrade

# 6. Run the development server
python run.py
# → Open http://localhost:5000
```

> **First run:** The first user to register automatically receives **admin** privileges.

---

## 🤖 Model Files

The inference models are **not included** in this repository (binary files, large size).

Place your OpenVINO-converted models in `models/ov/`:

```
models/ov/
├── yolo11n.xml          # Zone Detector — person detection (YOLO11n)
├── yolo11n.bin
├── rtmpose-t.xml        # Zone Detector — pose estimation (RTMPose-T)
├── rtmpose-t.bin
├── xg_detector.xml      # XG Detector — your proprietary model
└── xg_detector.bin
```

**Converting YOLO models to OpenVINO:**

```bash
# Install conversion tools
pip install openvino-dev ultralytics

# Export YOLO11n to OpenVINO
yolo export model=yolo11n.pt format=openvino half=True
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and edit:

```ini
FLASK_ENV=development
SECRET_KEY=your-secret-key-here   # Change in production!

# Model file paths (OpenVINO .xml)
DET_MODEL=models/ov/yolo11n.xml
POSE_MODEL=models/ov/rtmpose-t.xml
XG_MODEL=models/ov/xg_detector.xml

# Detection thresholds
DET_SCORE_THR=0.35       # Person detection confidence
POSE_KPT_THR=0.30        # Keypoint confidence for ankle detection
XG_CONFIDENCE_THR=0.45   # XG Detector alarm threshold

# Storage
UPLOAD_FOLDER=uploads
SNAPSHOT_FOLDER=snapshots
MAX_CONTENT_LENGTH=524288000   # 500 MB max upload
```

---

## 📁 Project Structure

```
zovid/
├── app/
│   ├── __init__.py          # Application factory — blueprints + model loading
│   ├── extensions.py        # SQLAlchemy, LoginManager, SocketIO instances
│   │
│   ├── api/                 # REST API endpoints
│   │   ├── sessions.py      # Start / stop / list detection sessions
│   │   ├── cameras.py       # Camera CRUD
│   │   ├── reports.py       # Violation reports + CSV export
│   │   ├── upload.py        # Video file upload
│   │   ├── filebrowser.py   # Uploaded video browser
│   │   └── training.py      # XG Detector training trigger
│   │
│   ├── auth/                # Authentication (login / register / logout)
│   ├── admin/               # Admin panel (users, cameras, system health)
│   ├── views/               # Page blueprints (dashboard, session, training)
│   │
│   ├── models/              # SQLAlchemy database models
│   │   ├── user.py          # User (role: admin / user)
│   │   ├── camera.py        # Camera source + zone polygons
│   │   ├── session.py       # Detection session metadata
│   │   └── violation.py     # Violation events + snapshot paths
│   │
│   ├── stream/              # Real-time streaming engine
│   │   └── manager.py       # StreamManager — per-session inference threads
│   │
│   ├── templates/           # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── auth/
│   │   ├── dashboard/
│   │   ├── session/
│   │   ├── report/
│   │   ├── training/
│   │   └── admin/
│   │
│   └── static/
│       ├── css/main.css     # Global stylesheet
│       └── js/
│           ├── dashboard.js # Camera grid + session control
│           ├── session.js   # Stream view + violation counter
│           ├── canvas.js    # Zone polygon drawing tool
│           ├── stream.js    # MJPEG + SocketIO stats handler
│           └── main.js      # Shared utilities
│
├── inference/
│   ├── detector.py                # YOLO11n person detector (OpenVINO)
│   ├── pose_estimator.py          # RTMPose-T ankle keypoint estimator (OpenVINO)
│   ├── zone_violation_detector.py # Polygon intersection logic
│   └── xg_detector_stub.py        # XG Detector plugin interface → implement here
│
├── migrations/              # Alembic DB migration scripts
├── models/ov/               # OpenVINO model files (not tracked by git)
├── uploads/                 # Uploaded video files (not tracked by git)
├── snapshots/               # Violation frame captures (not tracked by git)
│
├── config.py                # Flask config classes (Dev / Prod)
├── run.py                   # App entrypoint
├── requirements.txt
├── .env.example             # Environment variable template
└── start.bat                # Windows quick-start script
```

---

## 🔌 XG Detector — Plugin Interface

The XG Detector slot is designed to be filled with a proprietary or custom algorithm. The `xg_detector_stub.py` file defines the exact interface:

```python
class XGDetector:
    def _load(self) -> None:
        """Load / initialize your model here."""
        # e.g.  self._model = ov.compile_model(self._model_path, "AUTO")
        self._ready = True

    def process_image(
        self,
        frame: np.ndarray,
        conf_thres: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """
        Returns:
            boxes   : np.ndarray  (N, 4)   [x1, y1, x2, y2]
            scores  : np.ndarray  (N,)     confidence values
            classes : list[str]   (N,)     class label strings
        """
        ...
```

1. Copy `inference/xg_detector_stub.py` → `inference/xg_detector.py`
2. Implement `_load()` and `process_image()`
3. Restart the server — the pipeline activates automatically

---

## 🗃️ Database Schema

```
User ──< Session >── Camera
              │
              └──< Violation
```

| Table | Key Fields |
|---|---|
| `users` | id, username, email, password_hash, role, created_at |
| `cameras` | id, name, source_url, zone_polygon (JSON), created_by |
| `sessions` | id, camera_id, user_id, status, started_at, ended_at |
| `violations` | id, session_id, timestamp, snapshot_path, zone_name |

---

## 🚀 Deployment

### Production (Gunicorn + Nginx)

```bash
# Set production environment
export FLASK_ENV=production
export SECRET_KEY=<strong-random-key>
export DATABASE_URL=postgresql://user:pass@localhost/zovid

# Run with Gunicorn (eventlet worker)
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8000 "run:create_app()"
```

> ⚠️ Use exactly **1 worker** with the eventlet worker class — multiple workers break SocketIO room routing.

### Windows (Development)

```bat
start.bat
```

---

## 🤝 Contributing

Pull requests are welcome for the open-source parts of this project (web platform, stream pipeline, zone logic). For XG Detector integration, see the [plugin interface section](#-xg-detector--plugin-interface) above.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 👤 Author

**Rukiye Koruyucu**

[![GitHub](https://img.shields.io/badge/GitHub-rukiyekoruyucu-181717?style=flat-square&logo=github)](https://github.com/rukiyekoruyucu)

---

## 📄 License

This project's web platform, stream infrastructure, and zone detection integration layer are proprietary.  
The XG Detector algorithm implementation is **not included** — see [inference/xg_detector_stub.py](inference/xg_detector_stub.py) for the integration interface.

© 2024–2026 Rukiye Koruyucu. All rights reserved.

---

<div align="center">
  <sub>Built with ❤️ using Flask · OpenVINO · OpenCV</sub>
</div>
