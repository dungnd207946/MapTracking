import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'maptracking.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER PRIMARY KEY,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        name TEXT DEFAULT ''
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS edges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_node INTEGER NOT NULL,
        to_node INTEGER NOT NULL,
        street_name TEXT DEFAULT '',
        distance REAL NOT NULL,
        highway_type TEXT DEFAULT '',
        is_one_way INTEGER DEFAULT 0,
        status TEXT DEFAULT 'normal',
        geometry TEXT DEFAULT '[]',
        FOREIGN KEY (from_node) REFERENCES nodes(id),
        FOREIGN KEY (to_node) REFERENCES nodes(id)
    )''')

    conn.commit()
    conn.close()


def seed_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ("admin", generate_password_hash("admin123"), "admin"))
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ("user", generate_password_hash("user123"), "user"))
        conn.commit()
    conn.close()


def authenticate(username, password):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if user and check_password_hash(user['password'], password):
        return dict(user)
    return None


def get_all_nodes():
    conn = get_db()
    nodes = [dict(row) for row in conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()]
    conn.close()
    return nodes


def get_all_edges():
    conn = get_db()
    edges = [dict(row) for row in conn.execute("SELECT * FROM edges ORDER BY id").fetchall()]
    conn.close()
    return edges


def update_edge_status(edge_id, status, is_one_way=None):
    conn = get_db()
    if is_one_way is not None:
        conn.execute("UPDATE edges SET status = ?, is_one_way = ? WHERE id = ?",
                     (status, int(is_one_way), edge_id))
    else:
        conn.execute("UPDATE edges SET status = ? WHERE id = ?", (status, edge_id))
    conn.commit()
    conn.close()


def node_count():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    conn.close()
    return count


def bulk_insert(nodes_data, edges_data):
    """Insert all nodes and edges in a single transaction."""
    conn = get_db()
    c = conn.cursor()

    c.executemany(
        "INSERT OR IGNORE INTO nodes (id, lat, lon, name) VALUES (?, ?, ?, ?)",
        [(n['id'], n['lat'], n['lon'], n['name']) for n in nodes_data]
    )

    c.executemany(
        "INSERT INTO edges (from_node, to_node, street_name, distance, highway_type, is_one_way, geometry) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(e['from_node'], e['to_node'], e['street_name'], e['distance'],
          e['highway_type'], e['is_one_way'], e['geometry']) for e in edges_data]
    )

    conn.commit()
    conn.close()
