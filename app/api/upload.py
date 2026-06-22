import os
import uuid
from pathlib import Path
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required

upload_bp = Blueprint('upload', __name__, url_prefix='/api')


def allowed_file(filename: str) -> bool:
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


@upload_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya bulunamadı'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Dosya adı boş'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Desteklenmeyen format. İzin verilenler: mp4, avi, mov, mkv'}), 400

    # Güvenli dosya adı — UUID kullan
    ext      = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    folder   = Path(current_app.config['UPLOAD_FOLDER'])
    folder.mkdir(parents=True, exist_ok=True)
    filepath = folder / filename
    file.save(str(filepath))

    return jsonify({
        'filename': filename,
        'path':     str(filepath),
        'size':     os.path.getsize(filepath),
    }), 201
