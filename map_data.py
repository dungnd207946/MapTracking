"""
Fetch real road network data from OpenStreetMap via Overpass API.
Builds a simplified intersection graph for pathfinding.
Covers the Hoàn Kiếm district area, Hanoi.
"""
import json
import math
import os
import requests
import database as db

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'osm_cache.json')

# Bounding box: Hoàn Kiếm district + surroundings
BBOX = (21.018, 105.843, 21.042, 105.862)

OVERPASS_QUERY = f"""
[out:json][timeout:60];
(
  way["highway"~"^(primary|secondary|tertiary|residential|unclassified|living_street|trunk|trunk_link|primary_link|secondary_link|tertiary_link)$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out body;
>;
out skel qt;
"""


def haversine(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lon points."""
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_osm_data():
    """Fetch from Overpass API or load from cache."""
    if os.path.exists(CACHE_FILE):
        print("[map_data] Loading OSM data from cache...")
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    print("[map_data] Fetching OSM data from Overpass API...")
    try:
        resp = requests.post(OVERPASS_URL, data={"data": OVERPASS_QUERY}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch OSM data: {e}. Delete osm_cache.json to retry.")

    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    print(f"[map_data] Cached OSM data to {CACHE_FILE}")

    return data


def build_graph(osm_data):
    """
    Parse OSM response into an intersection graph.
    Returns (nodes_list, edges_list) ready for database insertion.
    """
    osm_nodes = {}
    osm_ways = []

    for el in osm_data['elements']:
        if el['type'] == 'node':
            osm_nodes[el['id']] = {'lat': el['lat'], 'lon': el['lon']}
        elif el['type'] == 'way':
            osm_ways.append({
                'id': el['id'],
                'node_ids': el.get('nodes', []),
                'tags': el.get('tags', {}),
            })

    print(f"[map_data] OSM raw: {len(osm_nodes)} nodes, {len(osm_ways)} ways")

    # Count how many ways each node belongs to
    node_way_count = {}
    for way in osm_ways:
        for nid in way['node_ids']:
            node_way_count[nid] = node_way_count.get(nid, 0) + 1

    # Intersections: endpoints of ways + nodes shared by 2+ ways
    intersections = set()
    for way in osm_ways:
        if len(way['node_ids']) < 2:
            continue
        intersections.add(way['node_ids'][0])
        intersections.add(way['node_ids'][-1])
        for nid in way['node_ids']:
            if node_way_count.get(nid, 0) >= 2:
                intersections.add(nid)

    # Only keep intersections that have coordinates
    intersections = {nid for nid in intersections if nid in osm_nodes}

    # Build intersection name from crossing streets
    node_streets = {}
    for way in osm_ways:
        name = way['tags'].get('name', '')
        if not name:
            continue
        for nid in way['node_ids']:
            if nid in intersections:
                node_streets.setdefault(nid, set()).add(name)

    # Create graph nodes
    graph_nodes = []
    for nid in intersections:
        coords = osm_nodes[nid]
        streets = sorted(node_streets.get(nid, set()))
        if len(streets) >= 2:
            name = f"{streets[0]} - {streets[1]}"
        elif len(streets) == 1:
            name = streets[0]
        else:
            name = ""
        graph_nodes.append({
            'id': nid,
            'lat': coords['lat'],
            'lon': coords['lon'],
            'name': name,
        })

    # Create graph edges by splitting ways at intersections
    graph_edges = []
    seen_edges = set()

    for way in osm_ways:
        nids = way['node_ids']
        if len(nids) < 2:
            continue

        street_name = way['tags'].get('name', 'Không tên')
        highway_type = way['tags'].get('highway', '')
        oneway_tag = way['tags'].get('oneway', 'no')
        is_one_way = 1 if oneway_tag == 'yes' else 0
        reverse_oneway = oneway_tag == '-1'

        # Walk through way nodes, split at intersections
        segment = [nids[0]]
        for nid in nids[1:]:
            segment.append(nid)
            if nid in intersections and len(segment) >= 2 and segment[0] in intersections:
                from_id = segment[0]
                to_id = segment[-1]

                if from_id == to_id:
                    segment = [nid]
                    continue

                # Compute distance along segment
                dist = 0
                geometry = []
                valid = True
                for i, snid in enumerate(segment):
                    if snid not in osm_nodes:
                        valid = False
                        break
                    c = osm_nodes[snid]
                    geometry.append([c['lat'], c['lon']])
                    if i > 0:
                        prev = osm_nodes[segment[i - 1]]
                        dist += haversine(prev['lat'], prev['lon'], c['lat'], c['lon'])

                if not valid or dist < 0.5:
                    segment = [nid]
                    continue

                if reverse_oneway:
                    from_id, to_id = to_id, from_id
                    geometry = list(reversed(geometry))

                edge_key = (from_id, to_id, street_name)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    graph_edges.append({
                        'from_node': from_id,
                        'to_node': to_id,
                        'street_name': street_name,
                        'distance': round(dist, 1),
                        'highway_type': highway_type,
                        'is_one_way': is_one_way,
                        'geometry': json.dumps(geometry),
                    })

                segment = [nid]

    print(f"[map_data] Graph: {len(graph_nodes)} intersections, {len(graph_edges)} edges")
    return graph_nodes, graph_edges


def initialize_map():
    """Populate database with real OSM data if empty."""
    if db.node_count() > 0:
        return

    osm_data = fetch_osm_data()
    nodes, edges = build_graph(osm_data)
    db.bulk_insert(nodes, edges)
    print(f"[map_data] Database populated: {len(nodes)} nodes, {len(edges)} edges")
