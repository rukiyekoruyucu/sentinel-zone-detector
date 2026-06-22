# coding: utf-8
"""
filebrowser.py — Sunucu tarafli dosya gezgini API.
Kullanicinin belirlenen kok klasorlerdeki video dosyalarini gezinmesini saglar.
"""
import os
from pathlib import Path
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required

filebrowser_bp = Blueprint('filebrowser', __name__, url_prefix='/api/files')

VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.mts'}


def _get_allowed_roots():
    """Config'deki ya da varsayilan kok klasorler."""
    cfg_roots = current_app.config.get('ALLOWED_BROWSE_ROOTS', [])
    if cfg_roots:
        return [Path(r) for r in cfg_roots]
    # Varsayilan: kullanici Downloads, Videos, Desktop, Documents
    home = Path.home()
    defaults = [
        home / 'Downloads',
        home / 'Videos',
        home / 'Desktop',
        home / 'Documents',
        Path('C:/Users'),
    ]
    return [p for p in defaults if p.exists()]


def _is_allowed(path: Path) -> bool:
    """Yol izin verilen koklerden birinin altinda mi?"""
    roots = _get_allowed_roots()
    try:
        resolved = path.resolve()
        for root in roots:
            try:
                resolved.relative_to(root.resolve())
                return True
            except ValueError:
                continue
    except Exception:
        pass
    return False


def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.2f} GB"


@filebrowser_bp.route('/roots')
@login_required
def list_roots():
    """Izin verilen kok klasorleri listele."""
    roots = _get_allowed_roots()
    return jsonify({
        'roots': [
            {'path': str(r), 'name': r.name or str(r), 'exists': r.exists()}
            for r in roots
        ]
    })


@filebrowser_bp.route('/browse')
@login_required
def browse():
    """
    Klasor icerigini listele.
    GET /api/files/browse?path=C:/Users/Rukiye/Downloads
    Dondurulenler: klasorler + video dosyalari
    """
    raw_path = request.args.get('path', '').strip()
    if not raw_path:
        # Kok klasorleri listele
        return list_roots()

    target = Path(raw_path)

    # Guvenlik: izin verilen kok altinda olmali
    if not _is_allowed(target):
        return jsonify({'error': 'Bu klasore erisim izniniz yok.'}), 403

    if not target.exists():
        return jsonify({'error': 'Klasor bulunamadi.'}), 404

    if not target.is_dir():
        return jsonify({'error': 'Bu bir klasor degil.'}), 400

    items = []
    try:
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        for entry in entries:
            try:
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir():
                    # Sadece erisilebilir klasorler
                    try:
                        next(entry.iterdir(), None)  # erisim testi
                    except PermissionError:
                        continue
                    items.append({
                        'name': entry.name,
                        'path': str(entry),
                        'type': 'dir',
                        'size': None,
                        'size_human': None,
                    })
                elif entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                    try:
                        sz = entry.stat().st_size
                    except OSError:
                        sz = 0
                    items.append({
                        'name':       entry.name,
                        'path':       str(entry),
                        'type':       'file',
                        'ext':        entry.suffix.lower(),
                        'size':       sz,
                        'size_human': _human_size(sz),
                    })
            except Exception:
                continue
    except PermissionError:
        return jsonify({'error': 'Bu klasore erisim izniniz yok.'}), 403

    # Breadcrumb olustur
    parts = []
    try:
        p = target.resolve()
        while True:
            parts.insert(0, {'name': p.name or str(p), 'path': str(p)})
            parent = p.parent
            if parent == p:
                break
            if not _is_allowed(parent):
                break
            p = parent
    except Exception:
        parts = [{'name': target.name, 'path': str(target)}]

    return jsonify({
        'path':      str(target),
        'parent':    str(target.parent) if _is_allowed(target.parent) else None,
        'breadcrumb': parts,
        'items':     items,
    })


@filebrowser_bp.route('/validate')
@login_required
def validate_path():
    """
    Verilen dosya yolunun gecerli video dosyasi olup olmadigini kontrol et.
    GET /api/files/validate?path=C:/Users/.../video.avi
    """
    raw = request.args.get('path', '').strip()
    if not raw:
        return jsonify({'valid': False, 'error': 'Yol bos olamaz.'}), 400

    p = Path(raw)
    if not _is_allowed(p):
        return jsonify({'valid': False, 'error': 'Erisim izniniz yok.'}), 403
    if not p.exists():
        return jsonify({'valid': False, 'error': 'Dosya bulunamadi.'}), 404
    if not p.is_file():
        return jsonify({'valid': False, 'error': 'Bu bir dosya degil.'}), 400
    if p.suffix.lower() not in VIDEO_EXTENSIONS:
        return jsonify({'valid': False, 'error': f'Desteklenmeyen format: {p.suffix}'}), 400

    try:
        size = p.stat().st_size
    except OSError:
        size = 0

    return jsonify({
        'valid':      True,
        'path':       str(p),
        'name':       p.name,
        'size':       size,
        'size_human': _human_size(size),
    })
