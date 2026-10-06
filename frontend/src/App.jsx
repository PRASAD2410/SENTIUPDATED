import React, {useEffect, useState, useRef, lazy, Suspense} from 'react';
import {LayoutGrid, Download, Network, Lightbulb, Database, Settings, LogOut, Plus, Search, Loader2, AlertCircle, RefreshCw, GitBranch} from 'lucide-react';
import {api, EMPTY, readSetting, Logo, ThemeButton, Modal} from './shared';
import Entry from './Entry';
import Overview from './Overview';
import InputView from './InputView';
const GraphView = lazy(() => import('./GraphView'));
const KnowledgeGraph = lazy(() => import('./KnowledgeGraph'));
import LeadsView from './LeadsView';
const IntelligenceDB = React.lazy(() => import('./IntelligenceDB'));
import CaseManagement from './CaseManagement';

const NAV = [
  ['overview', LayoutGrid, 'Overview'],
  ['input', Download, 'Input'],
  ['network', Network, 'Network Graph'],
  ['knowledge', GitBranch, 'Knowledge Graph'],
  ['leads', Lightbulb, 'Leads'],
  ['intelligence', Database, 'Intelligence DB']
];

function NewCase({close, created}) {
  const [title, setTitle] = useState('');
  const [classification, setClassification] = useState('Restricted');
  const [summary, setSummary] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      created(await api('/api/cases', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, classification, summary})
      }));
      close();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Create New Case" close={close}>
      <form onSubmit={submit}>
        <label className="field-label" htmlFor="case-title">CASE TITLE</label>
        <input id="case-title" required maxLength={150} value={title} onChange={e => setTitle(e.target.value)} placeholder="Enter case title"/>
        <label className="field-label" htmlFor="classification">CLASSIFICATION</label>
        <select id="classification" value={classification} onChange={e => setClassification(e.target.value)}>
          {['Restricted', 'Confidential', 'Internal'].map(x => <option key={x}>{x}</option>)}
        </select>
        <label className="field-label" htmlFor="summary">SUMMARY</label>
        <textarea id="summary" value={summary} onChange={e => setSummary(e.target.value)} placeholder="Brief case context and analytical objective" rows={3}/>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" onClick={close}>CANCEL</button>
          <button className="primary" disabled={busy || !title.trim()}>{busy ? 'CREATING…' : 'CREATE CASE'}</button>
        </div>
      </form>
    </Modal>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, info) {
    console.error('View render error:', error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="panel" style={{ margin: '2rem', padding: '2rem', textAlign: 'center' }}>
          <h3>Unable to display this view</h3>
          <p className="muted small" style={{ margin: '1rem 0' }}>{this.state.error?.message || 'An unexpected rendering error occurred.'}</p>
          <button className="primary" onClick={() => { this.setState({ hasError: false, error: null }); if (this.props.onRetry) this.props.onRetry(); }}>
            RELOAD VIEW
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [theme, setTheme] = useState(() => readSetting('sg-theme', 'light'));
  const [entered, setEntered] = useState(() => Boolean(readSetting('sg-auth-session', '')));
  const [view, setView] = useState(() => readSetting('sg-active-view', 'overview'));
  const [caseId, setCaseId] = useState(() => readSetting('sg-case', 'default'));
  const [cases, setCases] = useState([]);
  const [data, setData] = useState(EMPTY);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState('');
  const [revision, setRevision] = useState(0);
  const [caseSearch, setCaseSearch] = useState('');
  const loadedCase = useRef(null);

  const toggle = () => setTheme(t => t === 'light' ? 'dark' : 'light');

  const login = () => {
    try { localStorage.setItem('sg-auth-session', 'session-' + Date.now()); } catch {}
    setEntered(true);
  };

  const logout = () => {
    try { localStorage.removeItem('sg-auth-session'); } catch {}
    setEntered(false);
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('sg-theme', theme); } catch {}
  }, [theme]);

  useEffect(() => {
    try { localStorage.setItem('sg-case', caseId); } catch {}
  }, [caseId]);

  useEffect(() => {
    try { localStorage.setItem('sg-active-view', view); } catch {}
  }, [view]);

  useEffect(() => {
    if (!entered) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');

    if (loadedCase.current !== caseId) {
      setData(EMPTY);
      loadedCase.current = caseId;
    }

    Promise.allSettled([
      api('/health', {signal: controller.signal}),
      api('/api/cases', {signal: controller.signal}),
      api(`/api/cases/${encodeURIComponent(caseId)}/workspace`, {signal: controller.signal})
    ]).then(([h, c, w]) => {
      if (controller.signal.aborted) return;
      setHealth(h.status === 'fulfilled' ? h.value : null);
      if (c.status === 'fulfilled') {
        setCases(c.value.cases);
        if (caseId !== 'default' && !c.value.cases.some(x => x.id === caseId)) {
          setCaseId(c.value.cases[0]?.id || 'default');
        }
      } else {
        setCases([]);
      }
      if (w.status === 'fulfilled') {
        setData(w.value ? { ...EMPTY, ...w.value, network: { ...EMPTY.network, ...(w.value.network || {}) } } : EMPTY);
      } else {
        setData(EMPTY);
        setError(w.reason?.message || 'Failed to load case data');
      }
      setLoading(false);
    });

    return () => controller.abort();
  }, [entered, caseId, revision]);

  const current = cases.find(c => c.id === caseId) || {id: caseId, title: 'Case 1', classification: 'Restricted'};
  const refresh = () => setRevision(n => n + 1);

  const caseManaged = ({deleted, caseId: removed}) => {
    setModal('');
    setData(EMPTY);
    setView('overview');
    setCaseSearch('');
    try { localStorage.removeItem('sg-draft-' + removed); } catch {}
    if (deleted) {
      const remaining = cases.filter(c => c.id !== removed);
      setCases(remaining);
      setCaseId(remaining[0]?.id || 'default');
    }
    refresh();
  };

  const selectCase = id => {
    setCaseId(id);
    setView('overview');
  };

  if (!entered) return <Entry {...{theme, toggle}} enter={login}/>;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><Logo/></div>
        <div className="nav-group">
          <p className="micro">ANALYSIS WORKSPACE</p>
          {NAV.map(([id, Icon, title]) => (
            <button key={id} className={'nav-item ' + (view === id ? 'active' : '')} onClick={() => setView(id)}>
              <Icon size={18}/><span>{title}</span>
            </button>
          ))}
        </div>
        <div className="case-group">
          <div className="between micro"><span>CASES</span><span className="blue">{cases.length}</span></div>
          <div className="case-search">
            <Search size={13}/>
            <input aria-label="Search case titles" placeholder="Search cases" value={caseSearch} onChange={e => setCaseSearch(e.target.value)}/>
          </div>
          {cases.filter(c => (c.title + ' ' + c.id).toLowerCase().includes(caseSearch.toLowerCase())).map(c => (
            <button className={'case-item ' + (caseId === c.id ? 'selected' : '')} key={c.id} onClick={() => selectCase(c.id)}>
              <span title={c.title}>{c.title}<small>{c.id}</small></span>
              <em>{c.status || 'Active'}</em>
            </button>
          ))}
          {!cases.length && <p className="muted small">Create a case to organize your records.</p>}
          <button className="dashed-button" onClick={() => setModal('case')}>+ NEW CASE</button>
        </div>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => setModal('settings')}><Settings size={18}/>Settings</button>
          <button className="nav-item" onClick={logout}><LogOut size={18}/>Logout</button>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">SENTINELGRAPH / WORKSPACE</p>
            <h1>{NAV.find(x => x[0] === view)?.[2]}</h1>
          </div>
          <div className="header-actions">
            <button onClick={refresh} disabled={loading} title="Reload the selected case from MongoDB">
              <RefreshCw size={13} className={loading ? 'spin' : ''}/> REFRESH
            </button>
            <button disabled={loading || !!error || (!cases.some(c => c.id === caseId) && !data.documents?.length && !data.network?.nodes?.length && !data.network?.edges?.length)} onClick={() => setModal('manage')}>
              <Settings size={13}/> MANAGE CASE
            </button>
            <button onClick={() => setModal('case')}><Plus size={13}/> NEW CASE</button>
            <span className={'system-status ' + (health?.mongo?.connected ? '' : 'offline')}>
              <i/>{health ? (health.mongo?.connected ? 'SYSTEM ONLINE' : 'DATABASE OFFLINE') : 'API OFFLINE'}
            </span>
            <ThemeButton {...{theme, toggle}}/>
          </div>
        </header>

        {error && <div className="error-banner" role="alert"><AlertCircle size={16}/><span>{error}</span><button onClick={refresh}>RETRY</button></div>}
        {data.truncated && <div className="error-banner">Showing up to 1,000 records per collection. This view may omit additional records.</div>}
        {loading && <div className="loading-strip"><Loader2 size={14} className="spin"/> Loading case records…</div>}

        <ErrorBoundary key={caseId + "-" + view} onRetry={refresh}>
          {view === 'overview' && <Overview {...{data, current, refresh}} navigate={setView}/>}
          {view === 'input' && <InputView key={caseId} {...{data, current, refresh}}/>}
          {view === 'network' && (
            <Suspense fallback={<div className="loading-strip">Loading graph explorer…</div>}>
              <GraphView {...{data, current, theme, loading, error}}/>
            </Suspense>
          )}
          {view === 'knowledge' && (
            <Suspense fallback={<div className="loading-strip">Loading knowledge graph…</div>}>
              <KnowledgeGraph {...{data, current, theme}}/>
            </Suspense>
          )}
          {view === 'leads' && <LeadsView key={caseId} {...{data, current}}/>}
          {view === 'intelligence' && (
            <Suspense fallback={<div className="loading-strip">Loading intelligence graph…</div>}>
              <IntelligenceDB {...{theme}}/>
            </Suspense>
          )}
        </ErrorBoundary>

        <footer className="workspace-footer mono">
          SENTINELGRAPH · HUMAN REVIEW REQUIRED
          <span>{current.id} / {current.classification?.toUpperCase()}</span>
        </footer>
      </main>

      {modal === 'case' && (
        <NewCase close={() => setModal('')} created={c => {
          setCases(cs => [c, ...cs]);
          setCaseId(c.id);
          setView('input');
        }}/>
      )}
      {modal === 'manage' && <CaseManagement {...{current, data}} close={() => setModal('')} finished={caseManaged}/>}
      {modal === 'settings' && (
        <Modal title="Workspace Settings" close={() => setModal('')}>
          <label className="field-label">APPEARANCE</label>
          <div className="setting-row">
            <span>{theme === 'light' ? 'Light mode' : 'Dark mode'}</span>
            <ThemeButton {...{theme, toggle}}/>
          </div>
          <p className="muted small">Theme is saved on this device. This prototype uses demo access; authentication and user permissions are not configured.</p>
          <button onClick={refresh}>REFRESH CONNECTION</button>
        </Modal>
      )}
    </div>
  );
}






