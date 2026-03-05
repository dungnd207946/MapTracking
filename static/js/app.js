const STATUS_COLORS = {
    normal: 'rgba(100, 100, 100, 0.35)',
    congested: '#f59e0b',
    flooded: '#3b82f6',
    blocked: '#ef4444',
};

const STATUS_LABELS = {
    normal: 'Bình thường',
    congested: 'Tắc đường',
    flooded: 'Ngập lụt',
    blocked: 'Đường cấm',
};

class MapApp {
    constructor() {
        this.map = null;
        this.nodes = [];
        this.edges = [];
        this.nodeMap = {};
        this.edgeMap = {};

        this.edgeLayers = {};
        this.routeLayer = null;
        this.startMarker = null;
        this.endMarker = null;

        this.startNode = null;
        this.endNode = null;
        this.selectedEdge = null;

        this.init();
    }

    async init() {
        this.map = L.map('map', {zoomControl: true});

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
            maxZoom: 19,
        }).addTo(this.map);

        this.map.setView([21.030, 105.853], 16);

        await this.loadMap();
        this.drawEdges();
        this.setupInteraction();
        this.setupUI();
    }

    async loadMap() {
        const res = await fetch('/api/map');
        const data = await res.json();
        this.nodes = data.nodes;
        this.edges = data.edges;
        this.nodeMap = {};
        this.nodes.forEach(n => this.nodeMap[n.id] = n);
        this.edgeMap = {};
        this.edges.forEach(e => this.edgeMap[e.id] = e);

        if (data.center) {
            this.map.setView([data.center.lat, data.center.lon], 16);
        }
    }

    // ── Drawing ──

    drawEdges() {
        // Clear old layers
        Object.values(this.edgeLayers).forEach(l => this.map.removeLayer(l));
        this.edgeLayers = {};

        for (const edge of this.edges) {
            let geometry;
            try {
                geometry = typeof edge.geometry === 'string' ? JSON.parse(edge.geometry) : edge.geometry;
            } catch { continue; }
            if (!geometry || geometry.length < 2) continue;

            const isNormal = edge.status === 'normal' && !edge.is_one_way;
            const isStatusOnly = edge.status !== 'normal';
            const isOneWay = !!edge.is_one_way;

            // In user mode, only show edges with special status or one-way
            if (!IS_ADMIN && isNormal) continue;

            let color, weight, opacity, dashArray;

            if (IS_ADMIN) {
                color = isStatusOnly ? STATUS_COLORS[edge.status]
                    : isOneWay ? '#8b5cf6'
                    : STATUS_COLORS.normal;
                weight = isNormal ? 4 : 6;
                opacity = isNormal ? 0.4 : 0.8;
                dashArray = edge.status === 'blocked' ? '8, 6' : null;
            } else {
                color = isStatusOnly ? STATUS_COLORS[edge.status] : '#8b5cf6';
                weight = 5;
                opacity = 0.75;
                dashArray = edge.status === 'blocked' ? '8, 6' : null;
            }

            const polyline = L.polyline(geometry, {
                color,
                weight,
                opacity,
                dashArray,
                interactive: IS_ADMIN,
            }).addTo(this.map);

            if (!IS_ADMIN && (isStatusOnly || isOneWay)) {
                const fromNode = this.nodeMap[edge.from_node];
                const toNode = this.nodeMap[edge.to_node];
                let tip = edge.street_name;
                if (isStatusOnly) tip += ` (${STATUS_LABELS[edge.status]})`;
                if (isOneWay) tip += ' (một chiều)';
                polyline.bindTooltip(tip, {sticky: true});
            }

            if (IS_ADMIN) {
                polyline.bindTooltip(edge.street_name, {sticky: true});
                polyline.on('click', (e) => {
                    L.DomEvent.stopPropagation(e);
                    this.selectEdge(edge);
                });
            }

            this.edgeLayers[edge.id] = polyline;
        }
    }

    drawRoute(routeGeometry) {
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }
        if (!routeGeometry || routeGeometry.length < 2) return;

        // Glow layer
        const glow = L.polyline(routeGeometry, {
            color: '#3b82f6',
            weight: 10,
            opacity: 0.25,
            interactive: false,
        }).addTo(this.map);

        const main = L.polyline(routeGeometry, {
            color: '#3b82f6',
            weight: 5,
            opacity: 0.9,
            interactive: false,
        }).addTo(this.map);

        this.routeLayer = L.layerGroup([glow, main]).addTo(this.map);
        this.map.fitBounds(main.getBounds().pad(0.1));
    }

    clearRoute() {
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }
    }

    setMarker(type, node) {
        const isStart = type === 'start';
        const markerRef = isStart ? 'startMarker' : 'endMarker';

        if (this[markerRef]) {
            this.map.removeLayer(this[markerRef]);
            this[markerRef] = null;
        }

        if (!node) return;

        const label = isStart ? 'A' : 'B';
        const icon = L.divIcon({
            className: 'custom-marker',
            html: `<div class="marker-pin ${isStart ? 'marker-start' : 'marker-end'}" data-label="${label}"></div>`,
            iconSize: [30, 42],
            iconAnchor: [15, 42],
        });

        this[markerRef] = L.marker([node.lat, node.lon], {icon})
            .bindTooltip(node.name || `${node.lat.toFixed(5)}, ${node.lon.toFixed(5)}`)
            .addTo(this.map);
    }

    // ── Interaction ──

    setupInteraction() {
        if (IS_ADMIN) {
            this.map.on('click', () => this.deselectEdge());
        } else {
            this.map.on('click', (e) => this.onMapClick(e));
        }
    }

    findNearestNode(latlng) {
        let best = null;
        let bestDist = Infinity;
        for (const node of this.nodes) {
            const d = this.map.distance(latlng, L.latLng(node.lat, node.lon));
            if (d < bestDist) {
                bestDist = d;
                best = node;
            }
        }
        return bestDist < 300 ? best : null;
    }

    onMapClick(e) {
        const node = this.findNearestNode(e.latlng);
        if (!node) return;
        this.selectPoint(node);
    }

    selectPoint(node) {
        if (this.startNode === null) {
            this.startNode = node;
            this.setMarker('start', node);
            this.setInput('search-start', node.name);
            this.setLabel('start-label', node.name);
        } else if (this.endNode === null) {
            if (node.id === this.startNode.id) return;
            this.endNode = node;
            this.setMarker('end', node);
            this.setInput('search-end', node.name);
            this.setLabel('end-label', node.name);
        } else {
            // Reset and set new start
            this.clearRoute();
            this.endNode = null;
            this.setMarker('end', null);
            this.setInput('search-end', '');
            this.setLabel('end-label', '');
            document.getElementById('route-result').style.display = 'none';

            this.startNode = node;
            this.setMarker('start', node);
            this.setInput('search-start', node.name);
            this.setLabel('start-label', node.name);
        }
        this.updateFindButton();
    }

    setInput(id, value) {
        const el = document.getElementById(id);
        if (el) el.value = value;
    }

    setLabel(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    updateFindButton() {
        const btn = document.getElementById('btn-find-route');
        if (btn) btn.disabled = !(this.startNode && this.endNode);
    }

    // ── Route Finding ──

    async findRoute() {
        if (!this.startNode || !this.endNode) return;

        const res = await fetch('/api/route', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({start: this.startNode.id, end: this.endNode.id}),
        });

        const data = await res.json();

        if (data.error) {
            this.clearRoute();
            const resultDiv = document.getElementById('route-result');
            resultDiv.style.display = 'block';
            document.getElementById('route-info').innerHTML =
                `<span style="color:#dc2626">${data.error}</span>`;
            document.getElementById('route-steps').innerHTML = '';
            return;
        }

        this.drawRoute(data.route_geometry);
        this.showRouteResult(data);
    }

    showRouteResult(data) {
        const resultDiv = document.getElementById('route-result');
        const infoDiv = document.getElementById('route-info');
        const stepsDiv = document.getElementById('route-steps');

        const distKm = (data.raw_distance / 1000).toFixed(2);
        const speedKmh = 25;
        const timeMin = Math.max(1, Math.round((data.raw_distance / 1000) / speedKmh * 60));

        infoDiv.innerHTML = `
            <strong>Khoảng cách:</strong> ${distKm} km<br>
            <strong>Thời gian ước tính:</strong> ~${timeMin} phút<br>
            <strong>Số ngã tư đi qua:</strong> ${data.path.length}
        `;

        let stepsHtml = '';
        for (let i = 0; i < data.path.length; i++) {
            const node = this.nodeMap[data.path[i]];
            if (!node) continue;
            const label = node.name || `(${node.lat.toFixed(5)}, ${node.lon.toFixed(5)})`;
            const icon = i === 0 ? '<span style="color:#16a34a">&#9679;</span>'
                : i === data.path.length - 1 ? '<span style="color:#dc2626">&#9679;</span>'
                : '<span style="color:#94a3b6">&rarr;</span>';
            stepsHtml += `<div class="step">${icon} ${label}</div>`;
        }
        stepsDiv.innerHTML = stepsHtml;
        resultDiv.style.display = 'block';
    }

    // ── Admin ──

    selectEdge(edge) {
        // Reset previous highlight
        if (this.selectedEdge && this.edgeLayers[this.selectedEdge.id]) {
            const prevEdge = this.selectedEdge;
            const isNormal = prevEdge.status === 'normal' && !prevEdge.is_one_way;
            this.edgeLayers[prevEdge.id].setStyle({
                color: prevEdge.status !== 'normal' ? STATUS_COLORS[prevEdge.status]
                    : prevEdge.is_one_way ? '#8b5cf6'
                    : STATUS_COLORS.normal,
                weight: isNormal ? 4 : 6,
            });
        }

        this.selectedEdge = edge;

        // Highlight selected
        if (this.edgeLayers[edge.id]) {
            this.edgeLayers[edge.id].setStyle({color: '#fbbf24', weight: 8});
            this.edgeLayers[edge.id].bringToFront();
        }

        this.showEdgeDetails(edge);
    }

    deselectEdge() {
        if (this.selectedEdge && this.edgeLayers[this.selectedEdge.id]) {
            const edge = this.selectedEdge;
            const isNormal = edge.status === 'normal' && !edge.is_one_way;
            this.edgeLayers[edge.id].setStyle({
                color: edge.status !== 'normal' ? STATUS_COLORS[edge.status]
                    : edge.is_one_way ? '#8b5cf6'
                    : STATUS_COLORS.normal,
                weight: isNormal ? 4 : 6,
            });
        }
        this.selectedEdge = null;
        document.getElementById('admin-selected').style.display = 'none';
        document.getElementById('admin-hint').style.display = 'block';
        document.querySelectorAll('.edge-list-item').forEach(el => el.classList.remove('active'));
    }

    showEdgeDetails(edge) {
        const panel = document.getElementById('admin-selected');
        const hint = document.getElementById('admin-hint');
        const info = document.getElementById('selected-edge-info');

        const a = this.nodeMap[edge.from_node];
        const b = this.nodeMap[edge.to_node];

        info.innerHTML = `
            <strong>${edge.street_name}</strong><br>
            Từ: ${a ? (a.name || 'N/A') : 'N/A'}<br>
            Đến: ${b ? (b.name || 'N/A') : 'N/A'}<br>
            Khoảng cách: ${(edge.distance).toFixed(0)} m<br>
            Loại đường: ${edge.highway_type}
        `;

        document.getElementById('edge-status').value = edge.status;
        document.getElementById('edge-oneway').checked = !!edge.is_one_way;

        panel.style.display = 'block';
        if (hint) hint.style.display = 'none';

        document.querySelectorAll('.edge-list-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.id) === edge.id);
        });
    }

    async updateEdge() {
        if (!this.selectedEdge) return;

        const status = document.getElementById('edge-status').value;
        const isOneWay = document.getElementById('edge-oneway').checked;

        const res = await fetch('/api/edge/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                edge_id: this.selectedEdge.id,
                status,
                is_one_way: isOneWay,
            }),
        });

        if (res.ok) {
            const edgeId = this.selectedEdge.id;
            await this.loadMap();
            this.drawEdges();
            this.populateEdgeList();
            const updated = this.edgeMap[edgeId];
            if (updated) {
                this.selectEdge(updated);
            }
        }
    }

    populateEdgeList() {
        const list = document.getElementById('edge-list');
        if (!list) return;

        // Sort: non-normal first, then by name
        const sorted = [...this.edges].sort((a, b) => {
            const sa = a.status === 'normal' ? 1 : 0;
            const sb = b.status === 'normal' ? 1 : 0;
            if (sa !== sb) return sa - sb;
            return a.street_name.localeCompare(b.street_name);
        });

        list.innerHTML = '';
        for (const edge of sorted) {
            const div = document.createElement('div');
            div.className = 'edge-list-item';
            div.dataset.id = edge.id;
            div.dataset.name = edge.street_name.toLowerCase();

            const statusClass = `status-${edge.status}`;
            const oneWayTag = edge.is_one_way ? ' &#8599;' : '';

            div.innerHTML = `
                <span class="edge-name">${edge.street_name}${oneWayTag}</span>
                <span class="edge-status ${statusClass}">${STATUS_LABELS[edge.status]}</span>
            `;

            div.addEventListener('click', () => {
                this.selectEdge(edge);
                // Pan map to edge
                const layer = this.edgeLayers[edge.id];
                if (layer) this.map.fitBounds(layer.getBounds().pad(0.3));
            });

            list.appendChild(div);
        }
    }

    // ── Search / UI ──

    setupUI() {
        if (IS_ADMIN) {
            this.setupAdmin();
        } else {
            this.setupUser();
        }
    }

    setupUser() {
        const btnFind = document.getElementById('btn-find-route');
        const btnClear = document.getElementById('btn-clear');

        if (btnFind) btnFind.addEventListener('click', () => this.findRoute());

        if (btnClear) {
            btnClear.addEventListener('click', () => {
                this.startNode = null;
                this.endNode = null;
                this.setMarker('start', null);
                this.setMarker('end', null);
                this.clearRoute();
                this.setInput('search-start', '');
                this.setInput('search-end', '');
                this.setLabel('start-label', '');
                this.setLabel('end-label', '');
                document.getElementById('route-result').style.display = 'none';
                this.updateFindButton();
            });
        }

        this.setupSearch('search-start', 'dropdown-start', (node) => {
            this.startNode = node;
            this.setMarker('start', node);
            this.setLabel('start-label', node.name);
            this.map.setView([node.lat, node.lon], 17);
            this.updateFindButton();
        });

        this.setupSearch('search-end', 'dropdown-end', (node) => {
            this.endNode = node;
            this.setMarker('end', node);
            this.setLabel('end-label', node.name);
            this.map.setView([node.lat, node.lon], 17);
            this.updateFindButton();
        });
    }

    setupSearch(inputId, dropdownId, onSelect) {
        const input = document.getElementById(inputId);
        const dropdown = document.getElementById(dropdownId);
        if (!input || !dropdown) return;

        // Only show named nodes in search
        const namedNodes = this.nodes.filter(n => n.name && n.name.length > 0);

        input.addEventListener('input', () => {
            const query = input.value.toLowerCase().trim();
            if (query.length < 2) {
                dropdown.classList.remove('active');
                return;
            }

            const matches = namedNodes.filter(n =>
                n.name.toLowerCase().includes(query)
            ).slice(0, 10);

            if (matches.length === 0) {
                dropdown.classList.remove('active');
                return;
            }

            dropdown.innerHTML = '';
            matches.forEach(node => {
                const div = document.createElement('div');
                div.className = 'search-dropdown-item';
                div.textContent = node.name;
                div.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    input.value = node.name;
                    dropdown.classList.remove('active');
                    onSelect(node);
                });
                dropdown.appendChild(div);
            });
            dropdown.classList.add('active');
        });

        input.addEventListener('blur', () => {
            setTimeout(() => dropdown.classList.remove('active'), 200);
        });

        input.addEventListener('focus', () => {
            if (input.value.trim().length >= 2) input.dispatchEvent(new Event('input'));
        });
    }

    setupAdmin() {
        const btnUpdate = document.getElementById('btn-update-edge');
        if (btnUpdate) btnUpdate.addEventListener('click', () => this.updateEdge());

        const filter = document.getElementById('edge-filter');
        if (filter) {
            filter.addEventListener('input', () => {
                const q = filter.value.toLowerCase();
                document.querySelectorAll('.edge-list-item').forEach(el => {
                    el.style.display = el.dataset.name.includes(q) ? '' : 'none';
                });
            });
        }

        this.populateEdgeList();
    }
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    window.mapApp = new MapApp();
});
