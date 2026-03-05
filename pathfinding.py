import heapq
import math


def haversine(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lon points."""
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def heuristic(node_a, node_b, nodes_map):
    a = nodes_map[node_a]
    b = nodes_map[node_b]
    return haversine(a['lat'], a['lon'], b['lat'], b['lon'])


HIGHWAY_WEIGHT = {
    'trunk': 0.8,
    'trunk_link': 0.9,
    'primary': 1.0,
    'primary_link': 1.1,
    'secondary': 1.2,
    'secondary_link': 1.3,
    'tertiary': 1.4,
    'tertiary_link': 1.5,
    'residential': 1.8,
    'unclassified': 2.0,
    'living_street': 2.5,
}

STATUS_WEIGHT = {
    'normal': 1.0,
    'congested': 3.0,
    'flooded': 5.0,
    'blocked': float('inf'),
}


def build_graph(edges):
    graph = {}
    for edge in edges:
        if edge['status'] == 'blocked':
            continue

        hw = HIGHWAY_WEIGHT.get(edge.get('highway_type', ''), 2.0)
        sw = STATUS_WEIGHT.get(edge['status'], 1.0)
        weight = edge['distance'] * hw * sw

        from_id = edge['from_node']
        to_id = edge['to_node']

        graph.setdefault(from_id, []).append((to_id, weight, edge['id']))

        if not edge['is_one_way']:
            graph.setdefault(to_id, []).append((from_id, weight, edge['id']))

    return graph


def find_path(start, end, nodes, edges):
    """
    A* pathfinding with haversine heuristic.
    Returns dict with path, edges, distance, route_geometry.
    """
    nodes_map = {n['id']: n for n in nodes}
    graph = build_graph(edges)

    if start not in nodes_map or end not in nodes_map:
        return None

    open_set = [(0, start)]
    came_from = {}
    edge_from = {}
    g_score = {start: 0}

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == end:
            path = [current]
            path_edges = []
            while current in came_from:
                path_edges.append(edge_from[current])
                current = came_from[current]
                path.append(current)
            path.reverse()
            path_edges.reverse()

            raw_dist = sum(
                haversine(
                    nodes_map[path[i]]['lat'], nodes_map[path[i]]['lon'],
                    nodes_map[path[i + 1]]['lat'], nodes_map[path[i + 1]]['lon']
                )
                for i in range(len(path) - 1)
            )

            return {
                'path': path,
                'edges': path_edges,
                'distance': round(g_score[end], 1),
                'raw_distance': round(raw_dist, 1),
            }

        if current not in graph:
            continue

        current_g = g_score[current]
        for neighbor, weight, edge_id in graph[current]:
            tentative_g = current_g + weight
            if tentative_g < g_score.get(neighbor, float('inf')):
                came_from[neighbor] = current
                edge_from[neighbor] = edge_id
                g_score[neighbor] = tentative_g
                f = tentative_g + heuristic(neighbor, end, nodes_map)
                heapq.heappush(open_set, (f, neighbor))

    return None
