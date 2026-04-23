"""Skills routes: /api/skills/list, /api/skills/<name> GET/PUT"""
import os
from flask import Blueprint, request, jsonify
from config import BASE, login_required

skills_bp = Blueprint('skills', __name__)
SKILLS_DIR = os.path.join(BASE, 'skills')


@skills_bp.route('/api/skills/list')
@login_required
def skills_list():
    if not os.path.isdir(SKILLS_DIR):
        return jsonify({'skills': []})
    files = sorted(f[:-3] for f in os.listdir(SKILLS_DIR) if f.endswith('.md'))
    return jsonify({'skills': files})


@skills_bp.route('/api/skills/<name>')
@login_required
def skills_get(name):
    if '/' in name or '\\' in name or '..' in name:
        return jsonify({'error': 'Invalid name'}), 400
    path = os.path.join(SKILLS_DIR, f'{name}.md')
    if not os.path.exists(path):
        return jsonify({'error': 'Not found'}), 404
    with open(path, encoding='utf-8') as f:
        return jsonify({'name': name, 'content': f.read()})


@skills_bp.route('/api/skills/<name>', methods=['PUT'])
@login_required
def skills_save(name):
    if '/' in name or '\\' in name or '..' in name:
        return jsonify({'error': 'Invalid name'}), 400
    content = (request.get_json() or {}).get('content', '')
    os.makedirs(SKILLS_DIR, exist_ok=True)
    path = os.path.join(SKILLS_DIR, f'{name}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return jsonify({'success': True})
