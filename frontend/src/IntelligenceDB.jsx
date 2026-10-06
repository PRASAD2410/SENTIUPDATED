import React, { useEffect, useRef, useState, useMemo } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import { Database, Users, Building2, CreditCard, Car, MapPin, RefreshCw, Search, Maximize, ZoomIn, ZoomOut, X } from 'lucide-react';
import { API } from './shared';

const TYPE_ICONS = { Person: Users, Organization: Building2, Account: CreditCard, Vehicle: Car, Location: MapPin };
const TYPE_COLORS = { Person: '#2453d4', Organization: '#207d91', Account: '#b26419', Vehicle: '#7b64b8', Location: '#7a889c' };
const STAT_CARDS = [
  { key: 'persons',       label: 'Persons',   icon: Users,       color: '#2453d4' },
  { key: 'accounts',      label: 'Accounts',  icon: CreditCard,  color: '#b26419' },
  { key: 'organizations', label: 'Companies', icon: Building2,   color: '#207d91' },
  { key: 'vehicles',      label: 'Vehicles',  icon: Car,         color: '#7b64b8' },
  { key: 'locations',     label: 'Locations', icon: MapPin,      color: '#7a889c' },
];

function graphStyles(theme) {
  const dark = theme === 'dark';
  const bg = dark ? '#1e1e2e' : '#f5f7ff';
  const txt = dark ? '#e2e8f0' : '#1a202c';
  return [
    { selector: 'node', style: { 'background-color': 'data(color)', label: 'data(label)', color: txt, 'text-valign': 'bottom', 'text-halign': 'center', 'font-size': 10, 'font-family': 'Arial, sans-serif', width: 28, height: 28, 'border-width': 2, 'border-color': dark ? '#2d3748' : '#fff', 'text-margin-y': 4, 'text-max-width': 90, 'text-wrap': 'ellipsis' } },
    { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#f59e0b', width: 36, height: 36 } },
    { selector: 'edge', style: { width: 1.5, 'line-color': dark ? '#4a5568' : '#cbd5e0', 'target-arrow-color': dark ? '#4a5568' : '#cbd5e0', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', label: 'data(label)', 'font-size': 8, color: '#718096', 'text-background-color': bg, 'text-background-opacity': 0.85, 'text-background-padding': 2 } },
    { selector: 'edge:selected', style: { 'line-color': '#f59e0b', 'target-arrow-color': '#f59e0b', width: 2.5 } },
  ];
}

function fitGraph(cy) {
  if (!cy || cy.destroyed() || !cy.nodes().length) return;
  cy.resize();
  const connected = cy.nodes().filter(n => n.degree() > 0);
  cy.fit(connected.length ? connected.union(cy.edges()) : cy.elements(), 55);
}

export default function IntelligenceDB({ theme }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [graphData, setGraphData] = useState({ nodes: [], edges: [], stats: {} });
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');
  const cyRef = useRef(null);

  const load = () => {
    setLoading(true); setError('');
    fetch(`${API}/api/intelligence-db/graph?limit=800`)
      .then(r => r.json())
      .then(d => { if (d.detail) throw new Error(d.detail); setGraphData(d); })
      .catch(e => setError(e.message || 'Failed to load intelligence database.'))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const typeMap = { persons: 'Person', accounts: 'Account', organizations: 'Organization', vehicles: 'Vehicle', locations: 'Location' };

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    const nodes = graphData.nodes.filter(n => {
      const matchType = typeFilter === 'All' || n.type === typeFilter;
      const matchSearch = !q || (n.label || '').toLowerCase().includes(q) || (n.id || '').toLowerCase().includes(q);
      return matchType && matchSearch;
    });
    const nodeIds = new Set(nodes.map(n => n.id));
    const edges = graphData.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    return { nodes, edges };
  }, [graphData, search, typeFilter]);

  const elements = useMemo(() => [
    ...filtered.nodes.map(n => ({ data: { id: n.id, label: (n.label || n.id).slice(0, 18), fullLabel: n.label || n.id, color: TYPE_COLORS[n.type] || '#7a889c', type: n.type, meta: n.meta } })),
    ...filtered.edges.map(e => ({ data: { id: 'e_' + e.id, source: e.source, target: e.target, label: (e.relation || '').replace(/_/g, ' ').toLowerCase() } })),
  ], [filtered]);

  const layout = useMemo(() => ({ name: 'cose', animate: false, randomize: true, nodeRepulsion: () => 8000, idealEdgeLength: () => 80, fit: true, padding: 50 }), [elements.length]);
  const stylesheet = useMemo(() => graphStyles(theme), [theme]);

  const init = cy => {
    if (cyRef.current === cy) return;
    cyRef.current = cy;
    cy.on('tap', 'node', e => { const d = e.target.data(); setSelected({ id: d.id, label: d.fullLabel, type: d.type, meta: d.meta || {} }); });
    cy.on('tap', e => { if (e.target === cy) setSelected(null); });
    cy.on('layoutstop', () => fitGraph(cy));
  };

  const Icon = selected ? (TYPE_ICONS[selected.type] || Database) : Database;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', gap: 10, padding: '12px 20px', flexWrap: 'wrap', borderBottom: '1px solid var(--border)', alignItems: 'center' }}>
        {STAT_CARDS.map(({ key, label, icon: I, color }) => (
          <div key={key}
            onClick={() => setTypeFilter(prev => prev === typeMap[key] ? 'All' : typeMap[key])}
            style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '7px 13px', borderRadius: 8, cursor: 'pointer', userSelect: 'none', background: 'var(--surface)', border: `1.5px solid ${typeFilter === typeMap[key] ? color : 'var(--border)'}`, transition: 'border-color .15s' }}>
            <I size={14} style={{ color }} />
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{graphData.stats[key] ?? '—'}</span>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</span>
          </div>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px' }}>
            <Search size={13} style={{ color: 'var(--muted)' }} />
            <input placeholder="Search entities…" value={search} onChange={e => setSearch(e.target.value)} style={{ border: 'none', background: 'transparent', color: 'var(--text)', fontSize: 12, width: 150, outline: 'none' }} />
          </div>
          <button onClick={load} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: 'var(--surface)', border: '1px solid var(--border)', cursor: 'pointer', color: 'var(--text)' }}>
            <RefreshCw size={12} className={loading ? 'spin' : ''} /> REFRESH
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>
        <div style={{ flex: 1, position: 'relative', background: 'var(--bg)' }}>
          {loading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, zIndex: 10, background: 'var(--bg)' }}>
              <RefreshCw size={28} className="spin" style={{ color: '#2453d4' }} />
              <span style={{ fontSize: 13, color: 'var(--muted)' }}>Building knowledge graph from reference collections…</span>
            </div>
          )}
          {!loading && error && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
              <Database size={32} style={{ color: 'var(--muted)' }} />
              <p style={{ color: 'var(--muted)', fontSize: 13 }}>{error}</p>
              <button onClick={load} style={{ padding: '6px 16px', borderRadius: 6, cursor: 'pointer' }}>RETRY</button>
            </div>
          )}
          {!loading && !error && elements.length === 0 && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
              <Database size={32} style={{ color: 'var(--muted)' }} />
              <p style={{ color: 'var(--muted)', fontSize: 13 }}>No entities match. <button onClick={() => { setSearch(''); setTypeFilter('All'); }} style={{ color: '#2453d4', background: 'none', border: 'none', cursor: 'pointer' }}>Clear filters</button></p>
            </div>
          )}
          {!loading && !error && elements.length > 0 && (
            <CytoscapeComponent elements={elements} layout={layout} stylesheet={stylesheet} cy={init} style={{ width: '100%', height: '100%' }} />
          )}

          <div style={{ position: 'absolute', top: 12, left: 12, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 20, padding: '4px 12px', fontSize: 11, color: 'var(--muted)' }}>
            {filtered.nodes.length} entities · {filtered.edges.length} links · Reference DB
          </div>

          <div style={{ position: 'absolute', bottom: 16, left: 16, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 11 }}>
            {Object.entries(TYPE_COLORS).map(([t, c]) => (
              <span key={t} style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text)' }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: c, display: 'inline-block' }} />{t}
              </span>
            ))}
          </div>

          <div style={{ position: 'absolute', bottom: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {[
              { I: ZoomIn,  fn: () => cyRef.current?.zoom({ level: cyRef.current.zoom() * 1.25, renderedPosition: { x: cyRef.current.width() / 2, y: cyRef.current.height() / 2 } }) },
              { I: ZoomOut, fn: () => cyRef.current?.zoom({ level: cyRef.current.zoom() * 0.8,  renderedPosition: { x: cyRef.current.width() / 2, y: cyRef.current.height() / 2 } }) },
              { I: Maximize, fn: () => fitGraph(cyRef.current) },
            ].map(({ I, fn }, i) => (
              <button key={i} onClick={fn} style={{ width: 32, height: 32, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                <I size={14} />
              </button>
            ))}
          </div>
        </div>

        {selected && (
          <div style={{ width: 280, borderLeft: '1px solid var(--border)', background: 'var(--surface)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', letterSpacing: '0.06em' }}>ENTITY PROFILE</span>
              <button onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted)' }}><X size={14} /></button>
            </div>
            <div style={{ padding: 16, flex: 1, overflowY: 'auto' }}>
              <div style={{ width: 52, height: 52, borderRadius: '50%', background: (TYPE_COLORS[selected.type] || '#7a889c') + '22', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 12px', border: `2px solid ${TYPE_COLORS[selected.type] || '#7a889c'}` }}>
                <Icon size={22} style={{ color: TYPE_COLORS[selected.type] || '#7a889c' }} />
              </div>
              <p style={{ textAlign: 'center', fontWeight: 700, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>{selected.label}</p>
              <p style={{ textAlign: 'center', fontSize: 11, color: TYPE_COLORS[selected.type] || '#7a889c', marginBottom: 16, fontWeight: 600 }}>{(selected.type || '').toUpperCase()}</p>
              <div style={{ background: 'var(--bg)', borderRadius: 8, padding: 12, border: '1px solid var(--border)' }}>
                <p style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', marginBottom: 8, letterSpacing: '0.06em' }}>RECORD DETAILS</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div>
                    <span style={{ fontSize: 10, color: 'var(--muted)' }}>ID</span>
                    <p style={{ fontSize: 12, color: 'var(--text)', fontFamily: 'Courier New, monospace', wordBreak: 'break-all', margin: 0 }}>{selected.id}</p>
                  </div>
                  {Object.entries(selected.meta || {}).filter(([, v]) => v).map(([k, v]) => (
                    <div key={k}>
                      <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase' }}>{k.replace(/_/g, ' ')}</span>
                      <p style={{ fontSize: 12, color: 'var(--text)', wordBreak: 'break-all', margin: 0 }}>{String(v)}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div style={{ marginTop: 12, padding: 10, background: '#2453d422', borderRadius: 8, border: '1px solid #2453d433' }}>
                <p style={{ fontSize: 11, color: '#2453d4', lineHeight: 1.5, margin: 0 }}>Reference record from ingested Stage B dataset. Upload FIR/CDR files to cross-reference with extracted case findings.</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
