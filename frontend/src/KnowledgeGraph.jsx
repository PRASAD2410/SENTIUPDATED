import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  forceSimulation, forceManyBody, forceLink, forceCenter,
  forceCollide, forceRadial, forceX, forceY
} from 'd3-force';
import {
  Search, ZoomIn, ZoomOut, Maximize2, RefreshCw, X,
  Filter, Info, SlidersHorizontal, Layers
} from 'lucide-react';

// ── colour palette ────────────────────────────────────────────────────────────
const TYPE_COLORS = {
  Person:       '#6366f1',
  Organization: '#f59e0b',
  Phone:        '#10b981',
  Account:      '#3b82f6',
  Vehicle:      '#ef4444',
  Location:     '#8b5cf6',
  UPI:          '#06b6d4',
  Domain:       '#ec4899',
  ExternalRef:  '#64748b',
  Event:        '#f97316',
};
const DEFAULT_COLOR = '#94a3b8';

function getColor(type) { return TYPE_COLORS[type] || DEFAULT_COLOR; }

// ── tiny helpers ──────────────────────────────────────────────────────────────
function shortLabel(label = '', max = 18) {
  if (!label) return '?';
  return label.length > max ? label.slice(0, max - 1) + '…' : label;
}

function nodeRadius(degree, isolated) {
  if (isolated) return 8;
  return Math.max(10, Math.min(30, 10 + Math.sqrt(degree) * 3));
}

// ── main component ────────────────────────────────────────────────────────────
export default function KnowledgeGraph({ data, current }) {
  const canvasRef   = useRef(null);
  const simRef      = useRef(null);
  const nodesRef    = useRef([]);
  const edgesRef    = useRef([]);
  const transformRef = useRef({ x: 0, y: 0, k: 1 });
  const hoveredRef  = useRef(null);
  const selectedRef = useRef(null);
  const dragRef     = useRef(null);
  const panRef      = useRef(null);
  const animRef     = useRef(null);
  const rafRef      = useRef(null);

  const [selected, setSelected]       = useState(null);
  const [search, setSearch]           = useState('');
  const [typeFilter, setTypeFilter]   = useState('All');
  const [showIsolated, setShowIsolated] = useState(true);
  const [zoom, setZoom]               = useState(1);
  const [stats, setStats]             = useState({ nodes: 0, edges: 0, types: [] });
  const [loading, setLoading]         = useState(true);
  const [searchResults, setSearchResults] = useState([]);

  const raw = data?.network || { nodes: [], edges: [] };

  // ── build graph data ──────────────────────────────────────────────────────
  const { simNodes, simEdges, degreeMap, allTypes } = useMemo(() => {
    const nodes = raw.nodes || [];
    const edges = raw.edges || [];

    const degreeMap = {};
    nodes.forEach(n => { degreeMap[n.id] = 0; });
    edges.forEach(e => {
      if (degreeMap[e.source] !== undefined) degreeMap[e.source]++;
      if (degreeMap[e.target] !== undefined) degreeMap[e.target]++;
    });

    const connectedIds = new Set(edges.flatMap(e => [e.source, e.target]));

    const simNodes = nodes.map(n => ({
      ...n,
      degree: degreeMap[n.id] || 0,
      isolated: !connectedIds.has(n.id),
      color: getColor(n.type),
      x: undefined,
      y: undefined,
      vx: 0,
      vy: 0,
    }));

    const idSet = new Set(simNodes.map(n => n.id));
    const simEdges = edges
      .filter(e => idSet.has(e.source) && idSet.has(e.target))
      .map(e => ({ ...e, source: e.source, target: e.target }));

    const allTypes = ['All', ...Array.from(new Set(nodes.map(n => n.type))).sort()];

    return { simNodes, simEdges, degreeMap, allTypes };
  }, [raw]);

  // ── filter visible nodes/edges ─────────────────────────────────────────────
  const { visNodes, visEdges } = useMemo(() => {
    let nodes = simNodes;
    if (typeFilter !== 'All') nodes = nodes.filter(n => n.type === typeFilter);
    if (!showIsolated) nodes = nodes.filter(n => !n.isolated);
    if (search) {
      const q = search.toLowerCase();
      nodes = nodes.filter(n => n.label?.toLowerCase().includes(q) || n.type?.toLowerCase().includes(q));
    }
    const visIds = new Set(nodes.map(n => n.id));
    const edges = simEdges.filter(e => {
      const s = typeof e.source === 'object' ? e.source.id : e.source;
      const t = typeof e.target === 'object' ? e.target.id : e.target;
      return visIds.has(s) && visIds.has(t);
    });
    return { visNodes: nodes, visEdges: edges };
  }, [simNodes, simEdges, typeFilter, showIsolated, search]);

  // ── search suggestions ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!search) { setSearchResults([]); return; }
    const q = search.toLowerCase();
    setSearchResults(
      simNodes.filter(n => n.label?.toLowerCase().includes(q)).slice(0, 8)
    );
  }, [search, simNodes]);

  // ── run d3-force simulation ────────────────────────────────────────────────
  useEffect(() => {
    if (!visNodes.length) { setLoading(false); return; }
    setLoading(true);

    const canvas = canvasRef.current;
    if (!canvas) return;
    const W = canvas.offsetWidth || 900;
    const H = canvas.offsetHeight || 600;
    const cx = W / 2, cy = H / 2;

    // Clone nodes so d3 can mutate them in place
    const nodeMap = {};
    const nodes = visNodes.map(n => {
      const prev = nodesRef.current.find(p => p.id === n.id);
      const clone = { ...n, x: prev?.x ?? cx + (Math.random() - .5) * 200, y: prev?.y ?? cy + (Math.random() - .5) * 200 };
      nodeMap[n.id] = clone;
      return clone;
    });

    const edges = visEdges.map(e => ({
      ...e,
      source: nodeMap[typeof e.source === 'object' ? e.source.id : e.source],
      target: nodeMap[typeof e.target === 'object' ? e.target.id : e.target],
    })).filter(e => e.source && e.target);

    nodesRef.current = nodes;
    edgesRef.current = edges;

    if (simRef.current) simRef.current.stop();

    const INNER_R = Math.min(W, H) * 0.28;
    const OUTER_R = Math.min(W, H) * 0.48;

    const sim = forceSimulation(nodes)
      .force('link', forceLink(edges).id(d => d.id).distance(d => {
        const sr = nodeRadius(d.source.degree, d.source.isolated);
        const tr = nodeRadius(d.target.degree, d.target.isolated);
        return 40 + sr + tr;
      }).strength(0.5))
      .force('charge', forceManyBody().strength(d => d.isolated ? -40 : -120))
      .force('center', forceCenter(cx, cy).strength(0.05))
      .force('collide', forceCollide().radius(d => nodeRadius(d.degree, d.isolated) + 6).strength(0.8))
      // connected nodes pulled inward
      .force('innerPull', forceRadial(INNER_R, cx, cy).strength(d => d.isolated ? 0 : 0.08))
      // isolated nodes pushed outward
      .force('outerPush', forceRadial(OUTER_R, cx, cy).strength(d => d.isolated ? 0.12 : 0))
      .alphaDecay(0.02)
      .velocityDecay(0.4);

    simRef.current = sim;

    let ticks = 0;
    sim.on('tick', () => {
      ticks++;
      drawFrame();
      if (ticks > 10) setLoading(false);
    });

    sim.on('end', () => { setLoading(false); drawFrame(); });

    return () => { sim.stop(); };
  }, [visNodes, visEdges]);

  // ── draw ───────────────────────────────────────────────────────────────────
  const drawFrame = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr;
    const H = canvas.height / dpr;
    const { x: tx, y: ty, k } = transformRef.current;

    ctx.save();
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // subtle radial bg gradient
    const grd = ctx.createRadialGradient(W/2, H/2, 0, W/2, H/2, Math.max(W,H)*0.6);
    grd.addColorStop(0, 'rgba(15,23,42,1)');
    grd.addColorStop(1, 'rgba(7,10,20,1)');
    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // draw subtle orbit rings (guidance)
    const cx = W/2 + tx, cy = H/2 + ty;
    const INNER_R = Math.min(W, H) * 0.28 * k;
    const OUTER_R = Math.min(W, H) * 0.48 * k;
    ctx.strokeStyle = 'rgba(99,102,241,0.07)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 8]);
    ctx.beginPath(); ctx.arc(cx, cy, INNER_R, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, OUTER_R, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);

    ctx.save();
    ctx.translate(W/2 + tx, H/2 + ty);
    ctx.scale(k, k);
    ctx.translate(-W/2, -H/2);

    const nodes = nodesRef.current;
    const edges = edgesRef.current;
    const hovered = hoveredRef.current;
    const sel = selectedRef.current;

    // Highlight set
    const highlightIds = new Set();
    if (sel) {
      highlightIds.add(sel.id);
      edges.forEach(e => {
        const sid = typeof e.source === 'object' ? e.source.id : e.source;
        const tid = typeof e.target === 'object' ? e.target.id : e.target;
        if (sid === sel.id) highlightIds.add(tid);
        if (tid === sel.id) highlightIds.add(sid);
      });
    }
    const dimming = highlightIds.size > 0;

    // Draw edges
    edges.forEach(e => {
      const src = typeof e.source === 'object' ? e.source : nodes.find(n => n.id === e.source);
      const tgt = typeof e.target === 'object' ? e.target : nodes.find(n => n.id === e.target);
      if (!src || !tgt || !src.x || !tgt.x) return;

      const highlighted = dimming && (highlightIds.has(src.id) && highlightIds.has(tgt.id));
      const alpha = dimming ? (highlighted ? 0.85 : 0.06) : 0.25;

      ctx.beginPath();
      ctx.moveTo(src.x, src.y);
      ctx.lineTo(tgt.x, tgt.y);
      ctx.strokeStyle = highlighted
        ? `rgba(99,102,241,${alpha})`
        : `rgba(148,163,184,${alpha})`;
      ctx.lineWidth = highlighted ? 1.5 / k : 0.8 / k;
      ctx.stroke();

      // edge label on hover/select
      if (highlighted && e.type) {
        const mx = (src.x + tgt.x) / 2;
        const my = (src.y + tgt.y) / 2;
        ctx.font = `${9 / k}px Inter,sans-serif`;
        ctx.fillStyle = 'rgba(148,163,184,0.7)';
        ctx.textAlign = 'center';
        ctx.fillText(e.type.replace(/_/g, ' '), mx, my - 4 / k);
      }
    });

    // Draw nodes
    nodes.forEach(n => {
      if (!n.x) return;
      const r = nodeRadius(n.degree, n.isolated);
      const isHovered = hovered?.id === n.id;
      const isSel = sel?.id === n.id;
      const dimmed = dimming && !highlightIds.has(n.id);
      const alpha = dimmed ? 0.2 : 1;

      // glow on connected/selected
      if ((isSel || isHovered) && !dimmed) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 8 / k, 0, Math.PI * 2);
        const glowGrd = ctx.createRadialGradient(n.x, n.y, r, n.x, n.y, r + 12 / k);
        glowGrd.addColorStop(0, n.color + '60');
        glowGrd.addColorStop(1, 'transparent');
        ctx.fillStyle = glowGrd;
        ctx.fill();
      }

      // ring for isolated nodes
      if (n.isolated) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 2 / k, 0, Math.PI * 2);
        ctx.strokeStyle = n.color + (dimmed ? '33' : '55');
        ctx.lineWidth = 1 / k;
        ctx.stroke();
      }

      // circle fill
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.globalAlpha = alpha;
      const fillGrd = ctx.createRadialGradient(n.x - r*0.3, n.y - r*0.3, 0, n.x, n.y, r);
      fillGrd.addColorStop(0, lighten(n.color, 40));
      fillGrd.addColorStop(1, n.color);
      ctx.fillStyle = fillGrd;
      ctx.fill();

      // border
      ctx.strokeStyle = isSel ? '#fff' : isHovered ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.15)';
      ctx.lineWidth = (isSel ? 2.5 : 1.2) / k;
      ctx.stroke();
      ctx.globalAlpha = 1;

      // label
      if (!dimmed && k > 0.35) {
        const fontSize = Math.max(9, Math.min(13, 11 / k));
        ctx.font = `${isSel ? 600 : 500} ${fontSize}px Inter,sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        // shadow
        ctx.shadowColor = 'rgba(0,0,0,0.8)';
        ctx.shadowBlur = 4;
        ctx.fillStyle = isSel ? '#fff' : isHovered ? '#e2e8f0' : 'rgba(226,232,240,0.85)';
        ctx.fillText(shortLabel(n.label, isSel ? 22 : 16), n.x, n.y + r + 3 / k);
        ctx.shadowBlur = 0;
      }
    });

    ctx.restore();
    ctx.restore();
  }, []);

  // ── resize handler ─────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;

    const resize = () => {
      const W = canvas.offsetWidth;
      const H = canvas.offsetHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      drawFrame();
    };

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    return () => ro.disconnect();
  }, [drawFrame]);

  // ── RAF loop ───────────────────────────────────────────────────────────────
  useEffect(() => {
    let running = true;
    const loop = () => {
      if (!running) return;
      drawFrame();
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => { running = false; cancelAnimationFrame(rafRef.current); };
  }, [drawFrame]);

  // ── hit test ──────────────────────────────────────────────────────────────
  const hitTest = useCallback((ex, ey) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr;
    const H = canvas.height / dpr;
    const { x: tx, y: ty, k } = transformRef.current;
    const gx = (ex - rect.left - W/2 - tx) / k + W/2;
    const gy = (ey - rect.top  - H/2 - ty) / k + H/2;
    for (const n of nodesRef.current) {
      const r = nodeRadius(n.degree, n.isolated) + 6;
      if ((gx - n.x) ** 2 + (gy - n.y) ** 2 <= r * r) return n;
    }
    return null;
  }, []);

  // ── pointer events ─────────────────────────────────────────────────────────
  const onPointerDown = useCallback(e => {
    const node = hitTest(e.clientX, e.clientY);
    if (node) {
      dragRef.current = { node, ox: e.clientX - node.x * transformRef.current.k, oy: e.clientY - node.y * transformRef.current.k, moved: false };
      if (simRef.current) {
        const d3node = nodesRef.current.find(n => n.id === node.id);
        if (d3node) { d3node.fx = d3node.x; d3node.fy = d3node.y; }
        simRef.current.alphaTarget(0.3).restart();
      }
    } else {
      panRef.current = { sx: e.clientX - transformRef.current.x, sy: e.clientY - transformRef.current.y };
    }
    canvasRef.current.setPointerCapture(e.pointerId);
  }, [hitTest]);

  const onPointerMove = useCallback(e => {
    hoveredRef.current = hitTest(e.clientX, e.clientY);
    canvasRef.current.style.cursor = hoveredRef.current ? 'pointer' : 'grab';

    if (dragRef.current) {
      const canvas = canvasRef.current;
      const dpr = window.devicePixelRatio || 1;
      const W = canvas.width / dpr;
      const H = canvas.height / dpr;
      const { tx, ty, k } = { tx: transformRef.current.x, ty: transformRef.current.y, k: transformRef.current.k };
      const rect = canvas.getBoundingClientRect();
      const gx = (e.clientX - rect.left - W/2 - tx) / k + W/2;
      const gy = (e.clientY - rect.top  - H/2 - ty) / k + H/2;
      const d3node = nodesRef.current.find(n => n.id === dragRef.current.node.id);
      if (d3node) { d3node.fx = gx; d3node.fy = gy; }
      dragRef.current.moved = true;
    } else if (panRef.current) {
      transformRef.current.x = e.clientX - panRef.current.sx;
      transformRef.current.y = e.clientY - panRef.current.sy;
    }
  }, [hitTest]);

  const onPointerUp = useCallback(e => {
    if (dragRef.current) {
      if (!dragRef.current.moved) {
        const node = nodesRef.current.find(n => n.id === dragRef.current.node.id);
        const isSame = selectedRef.current?.id === node?.id;
        selectedRef.current = isSame ? null : node;
        setSelected(isSame ? null : node);
      }
      const d3node = nodesRef.current.find(n => n.id === dragRef.current.node.id);
      if (d3node) { d3node.fx = null; d3node.fy = null; }
      if (simRef.current) simRef.current.alphaTarget(0).restart();
      dragRef.current = null;
    }
    panRef.current = null;
    canvasRef.current?.releasePointerCapture(e.pointerId);
  }, []);

  // ── wheel zoom ─────────────────────────────────────────────────────────────
  const onWheel = useCallback(e => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr;
    const H = canvas.height / dpr;
    const mx = e.clientX - rect.left - W/2;
    const my = e.clientY - rect.top  - H/2;
    const { x, y, k } = transformRef.current;
    const newK = Math.max(0.08, Math.min(4, k * factor));
    transformRef.current = {
      x: mx - (mx - x) * (newK / k),
      y: my - (my - y) * (newK / k),
      k: newK,
    };
    setZoom(newK);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  // ── zoom controls ──────────────────────────────────────────────────────────
  const zoomBy = useCallback(factor => {
    const canvas = canvasRef.current;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr;
    const H = canvas.height / dpr;
    const { x, y, k } = transformRef.current;
    const newK = Math.max(0.08, Math.min(4, k * factor));
    transformRef.current = {
      x: -(W/2) * (newK - k) + x,
      y: -(H/2) * (newK - k) + y,
      k: newK,
    };
    setZoom(newK);
  }, []);

  const fitView = useCallback(() => {
    const nodes = nodesRef.current.filter(n => n.x);
    if (!nodes.length) return;
    const canvas = canvasRef.current;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr;
    const H = canvas.height / dpr;
    const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const pad = 60;
    const gw = maxX - minX + pad * 2, gh = maxY - minY + pad * 2;
    const k = Math.max(0.08, Math.min(2, Math.min(W / gw, H / gh)));
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    // smooth animate
    const start = performance.now();
    const from = { ...transformRef.current };
    const to = { x: W/2 - cx * k, y: H/2 - cy * k, k };
    const dur = 500;
    const ease = t => t < 0.5 ? 2*t*t : -1+(4-2*t)*t;
    const step = now => {
      const t = ease(Math.min(1, (now - start) / dur));
      transformRef.current = {
        x: from.x + (to.x - from.x) * t,
        y: from.y + (to.y - from.y) * t,
        k: from.k + (to.k - from.k) * t,
      };
      setZoom(transformRef.current.k);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, []);

  // ── stats ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    setStats({
      nodes: visNodes.length,
      edges: visEdges.length,
      types: [...new Set(visNodes.map(n => n.type))],
    });
  }, [visNodes, visEdges]);

  // ── selected node connections ──────────────────────────────────────────────
  const selEdges = selected ? edgesRef.current.filter(e => {
    const sid = typeof e.source === 'object' ? e.source.id : e.source;
    const tid = typeof e.target === 'object' ? e.target.id : e.target;
    return sid === selected.id || tid === selected.id;
  }) : [];

  const selNeighbors = selEdges.map(e => {
    const sid = typeof e.source === 'object' ? e.source.id : e.source;
    const tid = typeof e.target === 'object' ? e.target.id : e.target;
    const nid = sid === selected.id ? tid : sid;
    return { node: nodesRef.current.find(n => n.id === nid), edge: e };
  }).filter(x => x.node);

  return (
    <div style={styles.page}>
      {/* ── toolbar ── */}
      <div style={styles.toolbar}>
        <div style={styles.toolbarLeft}>
          <span style={styles.eyebrow}>{current?.id || 'case'} / KNOWLEDGE GRAPH</span>
          {/* search */}
          <div style={styles.searchWrap}>
            <Search size={14} style={{ color: '#64748b', flexShrink: 0 }} />
            <input
              style={styles.searchInput}
              placeholder="Search entities…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            {search && <button style={styles.clearBtn} onClick={() => setSearch('')}><X size={12}/></button>}
            {searchResults.length > 0 && (
              <div style={styles.dropdown}>
                {searchResults.map(n => (
                  <button key={n.id} style={styles.dropItem} onClick={() => {
                    setSelected(n); selectedRef.current = n; setSearch('');
                  }}>
                    <span style={{ ...styles.dot, background: getColor(n.type) }}/>
                    <span style={styles.dropLabel}>{n.label}</span>
                    <small style={styles.dropType}>{n.type}</small>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* type filter */}
          <div style={styles.filterWrap}>
            <Layers size={13} style={{ color: '#64748b' }}/>
            <select style={styles.select} value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
              {allTypes.map(t => <option key={t}>{t}</option>)}
            </select>
          </div>

          {/* isolated toggle */}
          <button
            style={{ ...styles.pill, ...(showIsolated ? {} : styles.pillActive) }}
            onClick={() => setShowIsolated(v => !v)}
            title="Toggle isolated (unconnected) nodes"
          >
            {showIsolated ? 'Connected + Isolated' : 'Connected Only'}
          </button>
        </div>

        <div style={styles.toolbarRight}>
          <span style={styles.statBadge}>
            {stats.nodes.toLocaleString()} nodes · {stats.edges.toLocaleString()} edges
          </span>
          {loading && <span style={styles.loadingDot}>⬤ Simulating…</span>}
        </div>
      </div>

      {/* ── canvas area ── */}
      <div style={styles.body}>
        <canvas
          ref={canvasRef}
          style={styles.canvas}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />

        {/* ── zoom controls ── */}
        <div style={styles.zoomBar}>
          <button style={styles.zoomBtn} onClick={() => zoomBy(1.25)} title="Zoom in"><ZoomIn size={16}/></button>
          <span style={styles.zoomPct}>{Math.round(zoom * 100)}%</span>
          <button style={styles.zoomBtn} onClick={() => zoomBy(1/1.25)} title="Zoom out"><ZoomOut size={16}/></button>
          <div style={styles.zoomDivider}/>
          <button style={styles.zoomBtn} onClick={fitView} title="Fit view"><Maximize2 size={15}/></button>
        </div>

        {/* ── orbit legend ── */}
        <div style={styles.orbitLegend}>
          <span style={styles.orbitRing} data-label="Connected (inner)">
            <span style={{ ...styles.orbitDot, borderColor: 'rgba(99,102,241,0.4)' }}/>
            <span>Connected cluster</span>
          </span>
          <span style={styles.orbitRing} data-label="Isolated (outer)">
            <span style={{ ...styles.orbitDot, borderColor: 'rgba(148,163,184,0.3)', borderStyle: 'dashed' }}/>
            <span>Isolated nodes</span>
          </span>
        </div>

        {/* ── type legend ── */}
        <div style={styles.legend}>
          {Object.entries(TYPE_COLORS).map(([t, c]) => (
            <span key={t} style={styles.legendItem}>
              <span style={{ ...styles.legendDot, background: c }}/>
              <span>{t}</span>
            </span>
          ))}
          <small style={styles.legendHint}>SCROLL TO ZOOM · DRAG TO PAN · CLICK NODE TO INSPECT</small>
        </div>

        {/* ── empty state ── */}
        {!loading && visNodes.length === 0 && (
          <div style={styles.emptyState}>
            <p style={styles.emptyTitle}>No entities to display</p>
            <p style={styles.emptyDesc}>Upload source files in the Input tab to populate the graph.</p>
          </div>
        )}
      </div>

      {/* ── node inspector panel ── */}
      {selected && (
        <aside style={styles.panel}>
          <div style={styles.panelHeader}>
            <p style={styles.eyebrow}>ENTITY INSPECTOR</p>
            <button style={styles.closeBtn} onClick={() => { setSelected(null); selectedRef.current = null; }}>
              <X size={15}/>
            </button>
          </div>

          <div style={styles.nodeHero}>
            <div style={{ ...styles.nodeIcon, background: getColor(selected.type) + '22', borderColor: getColor(selected.type) + '55' }}>
              <span style={{ color: getColor(selected.type), fontSize: 22 }}>●</span>
            </div>
            <div>
              <h2 style={styles.nodeName}>{selected.label}</h2>
              <p style={styles.nodeMeta}>{selected.type?.toUpperCase()} · {selected.isolated ? 'Isolated' : `${selEdges.length} connections`}</p>
            </div>
          </div>

          {selected.normalizedValue && selected.normalizedValue !== selected.label?.toLowerCase() && (
            <div style={styles.factRow}><span>Normalized</span><strong>{selected.normalizedValue}</strong></div>
          )}
          {selected.externalId && (
            <div style={styles.factRow}><span>External ID</span><strong style={styles.mono}>{selected.externalId}</strong></div>
          )}
          {selected.bank && (
            <div style={styles.factRow}><span>Bank</span><strong>{selected.bank}</strong></div>
          )}
          {selected.nationalId && (
            <div style={styles.factRow}><span>National ID</span><strong style={styles.mono}>{selected.nationalId}</strong></div>
          )}
          {selected.dob && (
            <div style={styles.factRow}><span>Date of Birth</span><strong>{selected.dob}</strong></div>
          )}
          {selected.address && (
            <div style={styles.factRow}><span>Address</span><strong style={{ fontSize: 11 }}>{selected.address}</strong></div>
          )}
          {selected.make && (
            <div style={styles.factRow}><span>Vehicle</span><strong>{selected.year} {selected.make} {selected.model}</strong></div>
          )}

          {selNeighbors.length > 0 && (
            <>
              <p style={{ ...styles.eyebrow, marginTop: 16 }}>CONNECTIONS ({selNeighbors.length})</p>
              <div style={styles.connList}>
                {selNeighbors.map(({ node: n, edge: e }) => (
                  <button key={e.id + n?.id} style={styles.connItem} onClick={() => {
                    selectedRef.current = n; setSelected(n);
                  }}>
                    <span style={{ ...styles.dot, background: getColor(n.type), flexShrink: 0 }}/>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={styles.connLabel}>{n.label}</div>
                      <div style={styles.connEdge}>{e.type?.replace(/_/g, ' ')}</div>
                    </div>
                    <small style={styles.connType}>{n.type}</small>
                  </button>
                ))}
              </div>
            </>
          )}

          {selected.isolated && (
            <div style={styles.isolatedNote}>
              <Info size={13} style={{ flexShrink: 0, color: '#64748b' }}/>
              <span>This entity has no extracted relationships yet. It appears in the outer ring.</span>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

// ── colour utilities ──────────────────────────────────────────────────────────
function lighten(hex, amount) {
  const num = parseInt(hex.replace('#',''), 16);
  const r = Math.min(255, (num >> 16) + amount);
  const g = Math.min(255, ((num >> 8) & 0xff) + amount);
  const b = Math.min(255, (num & 0xff) + amount);
  return `rgb(${r},${g},${b})`;
}

// ── styles ────────────────────────────────────────────────────────────────────
const styles = {
  page: { display:'flex', flexDirection:'column', height:'100%', background:'#0a0f1e', color:'#e2e8f0', fontFamily:'Inter,sans-serif', overflow:'hidden', position:'relative' },
  toolbar: { display:'flex', alignItems:'center', justifyContent:'space-between', padding:'10px 16px', borderBottom:'1px solid rgba(99,102,241,0.15)', background:'rgba(10,15,30,0.95)', backdropFilter:'blur(8px)', gap:12, flexWrap:'wrap', zIndex:10 },
  toolbarLeft: { display:'flex', alignItems:'center', gap:12, flex:1, flexWrap:'wrap' },
  toolbarRight: { display:'flex', alignItems:'center', gap:12 },
  eyebrow: { fontSize:10, fontWeight:700, letterSpacing:'0.1em', color:'#64748b', whiteSpace:'nowrap' },
  searchWrap: { position:'relative', display:'flex', alignItems:'center', gap:6, background:'rgba(30,41,59,0.8)', border:'1px solid rgba(99,102,241,0.2)', borderRadius:8, padding:'5px 10px', minWidth:200 },
  searchInput: { background:'transparent', border:'none', outline:'none', color:'#e2e8f0', fontSize:13, flex:1, minWidth:120 },
  clearBtn: { background:'none', border:'none', cursor:'pointer', color:'#64748b', padding:0, display:'flex' },
  dropdown: { position:'absolute', top:'110%', left:0, right:0, background:'#1e293b', border:'1px solid rgba(99,102,241,0.3)', borderRadius:8, overflow:'hidden', zIndex:100, boxShadow:'0 8px 32px rgba(0,0,0,0.5)' },
  dropItem: { display:'flex', alignItems:'center', gap:8, width:'100%', padding:'8px 12px', background:'none', border:'none', cursor:'pointer', color:'#e2e8f0', textAlign:'left', transition:'background 0.15s' },
  dropLabel: { flex:1, fontSize:13, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' },
  dropType: { color:'#64748b', fontSize:10, fontWeight:600, letterSpacing:'0.05em' },
  filterWrap: { display:'flex', alignItems:'center', gap:6, background:'rgba(30,41,59,0.8)', border:'1px solid rgba(99,102,241,0.2)', borderRadius:8, padding:'5px 10px' },
  select: { background:'transparent', border:'none', outline:'none', color:'#e2e8f0', fontSize:12, cursor:'pointer' },
  pill: { background:'rgba(30,41,59,0.8)', border:'1px solid rgba(99,102,241,0.2)', borderRadius:20, padding:'4px 12px', fontSize:11, fontWeight:600, letterSpacing:'0.05em', color:'#94a3b8', cursor:'pointer', transition:'all 0.2s' },
  pillActive: { background:'rgba(99,102,241,0.15)', borderColor:'rgba(99,102,241,0.5)', color:'#818cf8' },
  statBadge: { fontSize:11, color:'#64748b', fontWeight:600 },
  loadingDot: { fontSize:11, color:'#6366f1', animation:'pulse 1.5s infinite' },
  body: { flex:1, position:'relative', overflow:'hidden' },
  canvas: { width:'100%', height:'100%', display:'block', touchAction:'none' },
  zoomBar: { position:'absolute', bottom:60, right:20, display:'flex', flexDirection:'column', alignItems:'center', gap:4, background:'rgba(15,23,42,0.9)', border:'1px solid rgba(99,102,241,0.2)', borderRadius:10, padding:'6px', backdropFilter:'blur(8px)' },
  zoomBtn: { background:'none', border:'none', cursor:'pointer', color:'#94a3b8', padding:'4px 6px', display:'flex', borderRadius:6, transition:'color 0.15s' },
  zoomPct: { fontSize:10, color:'#64748b', fontWeight:700, width:36, textAlign:'center', fontVariantNumeric:'tabular-nums' },
  zoomDivider: { width:1, height:1, background:'rgba(99,102,241,0.2)', margin:'2px 0' },
  orbitLegend: { position:'absolute', top:14, right:20, display:'flex', gap:12, background:'rgba(10,15,30,0.8)', borderRadius:8, padding:'6px 12px', backdropFilter:'blur(6px)', border:'1px solid rgba(99,102,241,0.1)' },
  orbitRing: { display:'flex', alignItems:'center', gap:6, fontSize:10, color:'#64748b' },
  orbitDot: { width:14, height:14, borderRadius:'50%', border:'1.5px solid', display:'inline-block' },
  legend: { position:'absolute', bottom:14, left:'50%', transform:'translateX(-50%)', display:'flex', alignItems:'center', gap:14, flexWrap:'wrap', justifyContent:'center', background:'rgba(10,15,30,0.85)', borderRadius:20, padding:'7px 18px', backdropFilter:'blur(6px)', border:'1px solid rgba(99,102,241,0.1)' },
  legendItem: { display:'flex', alignItems:'center', gap:5, fontSize:10, color:'#94a3b8', fontWeight:600, letterSpacing:'0.03em' },
  legendDot: { width:8, height:8, borderRadius:'50%', display:'inline-block' },
  legendHint: { color:'#475569', fontSize:9, letterSpacing:'0.05em', marginLeft:8 },
  emptyState: { position:'absolute', inset:0, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', gap:8 },
  emptyTitle: { fontSize:18, fontWeight:600, color:'#475569' },
  emptyDesc: { fontSize:13, color:'#334155' },
  panel: { position:'absolute', top:0, right:0, bottom:0, width:320, background:'rgba(10,15,30,0.95)', borderLeft:'1px solid rgba(99,102,241,0.2)', backdropFilter:'blur(12px)', overflowY:'auto', padding:20, display:'flex', flexDirection:'column', gap:10 },
  panelHeader: { display:'flex', alignItems:'center', justifyContent:'space-between' },
  closeBtn: { background:'rgba(30,41,59,0.8)', border:'1px solid rgba(99,102,241,0.2)', borderRadius:6, cursor:'pointer', color:'#94a3b8', padding:'4px 6px', display:'flex' },
  nodeHero: { display:'flex', gap:14, alignItems:'flex-start', padding:'12px 0', borderBottom:'1px solid rgba(99,102,241,0.1)' },
  nodeIcon: { width:48, height:48, borderRadius:12, border:'1.5px solid', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 },
  nodeName: { margin:0, fontSize:16, fontWeight:700, color:'#f1f5f9', wordBreak:'break-word' },
  nodeMeta: { margin:'4px 0 0', fontSize:11, color:'#64748b', fontWeight:600, letterSpacing:'0.06em' },
  factRow: { display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:8, fontSize:12, padding:'5px 0', borderBottom:'1px solid rgba(255,255,255,0.04)', color:'#94a3b8' },
  mono: { fontFamily:'monospace', fontSize:11 },
  connList: { display:'flex', flexDirection:'column', gap:4, maxHeight:300, overflowY:'auto' },
  connItem: { display:'flex', alignItems:'center', gap:10, padding:'8px 10px', background:'rgba(30,41,59,0.5)', border:'1px solid rgba(99,102,241,0.1)', borderRadius:8, cursor:'pointer', textAlign:'left', color:'#e2e8f0', transition:'all 0.15s', width:'100%' },
  connLabel: { fontSize:13, fontWeight:600, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' },
  connEdge: { fontSize:10, color:'#6366f1', fontWeight:600, letterSpacing:'0.04em', marginTop:2 },
  connType: { color:'#475569', fontSize:10, fontWeight:700, letterSpacing:'0.05em' },
  dot: { width:8, height:8, borderRadius:'50%', display:'inline-block', flexShrink:0 },
  isolatedNote: { display:'flex', gap:8, padding:'10px 12px', background:'rgba(30,41,59,0.5)', borderRadius:8, border:'1px solid rgba(99,102,241,0.1)', fontSize:12, color:'#64748b', alignItems:'flex-start', lineHeight:1.5 },
};
