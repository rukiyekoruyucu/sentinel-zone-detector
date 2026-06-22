from flask import Blueprint, request, jsonify
from flask_login import login_required
from app.extensions import db
from app.models.camera import Camera, ZoneTemplate
from app.auth.decorators import admin_required

cameras_bp = Blueprint('cameras_api', __name__, url_prefix='/api/cameras')


@cameras_bp.route('', methods=['GET'])
@login_required
def list_cameras():
    cameras = Camera.query.filter_by(is_active=True).all()
    return jsonify([{
        'id': c.id, 'name': c.name,
        'source_type': c.source_type, 'source_value': c.source_value,
        'description': c.description,
    } for c in cameras])


@cameras_bp.route('', methods=['POST'])
@admin_required
def create_camera():
    data = request.get_json() or {}
    cam  = Camera(
        name         = data.get('name', 'Kamera'),
        source_type  = data.get('source_type', 'rtsp'),
        source_value = data.get('source_value', ''),
        description  = data.get('description', ''),
    )
    db.session.add(cam)
    db.session.commit()
    return jsonify({'id': cam.id, 'name': cam.name}), 201


@cameras_bp.route('/<int:camera_id>', methods=['DELETE'])
@admin_required
def delete_camera(camera_id):
    cam = Camera.query.get_or_404(camera_id)
    cam.is_active = False
    db.session.commit()
    return jsonify({'status': 'deleted'})


@cameras_bp.route('/<int:camera_id>/zones', methods=['GET'])
@login_required
def get_zones(camera_id):
    zones = ZoneTemplate.query.filter_by(camera_id=camera_id).all()
    return jsonify([{
        'id': z.id, 'name': z.name,
        'polygon': z.polygon, 'is_default': z.is_default,
    } for z in zones])


@cameras_bp.route('/<int:camera_id>/zones', methods=['POST'])
@login_required
def save_zone(camera_id):
    data = request.get_json() or {}
    z = ZoneTemplate(
        camera_id = camera_id,
        name      = data.get('name', 'Zone'),
        is_default= data.get('is_default', False),
    )
    z.polygon = data.get('polygon', [])
    db.session.add(z)
    db.session.commit()
    return jsonify({'id': z.id, 'name': z.name}), 201
