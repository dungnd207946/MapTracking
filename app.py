import json
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import database as db
import pathfinding
from map_data import initialize_map

app = Flask(__name__)
app.secret_key = 'maptracking-secret-key-2024'


@app.before_request
def require_login():
    allowed = ['login', 'static']
    if request.endpoint and request.endpoint not in allowed and 'user_id' not in session:
        return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        user = db.authenticate(username, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            return redirect(url_for('index'))
        return render_template('login.html', error='Sai tên đăng nhập hoặc mật khẩu')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/admin')
def admin():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    return render_template('admin.html')


@app.route('/api/map')
def api_map():
    nodes = db.get_all_nodes()
    edges = db.get_all_edges()

    # Compute map center from node coordinates
    if nodes:
        avg_lat = sum(n['lat'] for n in nodes) / len(nodes)
        avg_lon = sum(n['lon'] for n in nodes) / len(nodes)
    else:
        avg_lat, avg_lon = 21.030, 105.853

    return jsonify({
        'nodes': nodes,
        'edges': edges,
        'center': {'lat': avg_lat, 'lon': avg_lon},
    })


@app.route('/api/route', methods=['POST'])
def api_route():
    data = request.get_json()
    start = data.get('start')
    end = data.get('end')

    if start is None or end is None:
        return jsonify({'error': 'Thiếu điểm đầu hoặc điểm cuối'}), 400

    nodes = db.get_all_nodes()
    edges = db.get_all_edges()

    result = pathfinding.find_path(start, end, nodes, edges)
    if result is None:
        return jsonify({'error': 'Không tìm được đường đi. Có thể đường bị chặn.'}), 404

    # Build route geometry from edge geometries
    edges_map = {e['id']: e for e in edges}
    route_geometry = _build_route_geometry(result['path'], result['edges'], edges_map)
    result['route_geometry'] = route_geometry

    return jsonify(result)


def _build_route_geometry(path, edge_ids, edges_map):
    """Stitch edge geometries into a continuous route polyline."""
    geometry = []
    for i, edge_id in enumerate(edge_ids):
        edge = edges_map[edge_id]
        geo = json.loads(edge['geometry'])
        if not geo:
            continue

        current_node = path[i]
        if edge['from_node'] != current_node:
            geo = list(reversed(geo))

        if geometry:
            geometry.extend(geo[1:])
        else:
            geometry.extend(geo)

    return geometry


@app.route('/api/edge/update', methods=['POST'])
def api_edge_update():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Không có quyền'}), 403

    data = request.get_json()
    edge_id = data.get('edge_id')
    status = data.get('status', 'normal')
    is_one_way = data.get('is_one_way')

    valid_statuses = ['normal', 'congested', 'flooded', 'blocked']
    if status not in valid_statuses:
        return jsonify({'error': f'Trạng thái không hợp lệ. Chọn: {valid_statuses}'}), 400

    db.update_edge_status(edge_id, status, is_one_way)
    return jsonify({'success': True})


if __name__ == '__main__':
    db.init_db()
    db.seed_users()
    initialize_map()
    app.run(debug=True, port=5000)
