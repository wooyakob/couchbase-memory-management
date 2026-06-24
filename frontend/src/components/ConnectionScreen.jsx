import { useState, useEffect } from 'react'
import { api } from '../api'

const C = {
  bg: '#0d1117', surface: '#161b22', elevated: '#1c2333',
  border: '#30363d', borderFocus: '#388bfd',
  text: '#e6edf3', muted: '#8b949e', faint: '#6e7681',
  blue: '#58a6ff', cbRed: '#EA2328', green: '#3fb950',
  red: '#f87171',
}

const S = {
  page: {
    minHeight: '100vh', background: C.bg,
    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
    padding: '24px',
  },
  logo: {
    display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '40px',
  },
  logoMark: {
    width: '40px', height: '40px', borderRadius: '10px',
    overflow: 'hidden',
  },
  logoText: {
    fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: '22px', color: C.text,
    letterSpacing: '-0.03em',
  },
  tagline: { color: C.muted, fontSize: '13px', marginTop: '2px' },
  card: {
    width: '100%', maxWidth: '480px',
    background: C.surface, border: `1px solid ${C.border}`, borderRadius: '16px',
    overflow: 'hidden',
    boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
  },
  cardHeader: {
    padding: '20px 24px 0',
  },
  stepRow: {
    display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '18px',
  },
  stepDot: (active, done) => ({
    width: '24px', height: '24px', borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: '11px', fontWeight: 700,
    background: done ? C.green : active ? C.cbRed : C.elevated,
    color: done || active ? '#fff' : C.faint,
    border: `1px solid ${done ? C.green : active ? C.cbRed : C.border}`,
    transition: 'all 0.2s',
    flexShrink: 0,
  }),
  stepLabel: (active) => ({
    fontSize: '12px', fontWeight: 500,
    color: active ? C.text : C.faint,
  }),
  stepLine: {
    flex: 1, height: '1px', background: C.border,
  },
  cardBody: { padding: '0 24px 24px' },
  fieldGroup: { marginBottom: '16px' },
  label: {
    display: 'block', fontSize: '12px', fontWeight: 500,
    color: C.muted, marginBottom: '6px', letterSpacing: '0.02em',
  },
  input: {
    width: '100%', padding: '9px 12px',
    background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '8px',
    color: C.text, fontSize: '13.5px', outline: 'none',
    transition: 'border-color 0.15s',
  },
  select: {
    width: '100%', padding: '9px 12px',
    background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '8px',
    color: C.text, fontSize: '13.5px', outline: 'none',
    appearance: 'none', cursor: 'pointer',
    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%238b949e' d='M6 8L1 3h10z'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center',
  },
  toggleRow: {
    display: 'flex', borderRadius: '8px', overflow: 'hidden',
    border: `1px solid ${C.border}`, marginBottom: '16px',
  },
  toggleBtn: (active) => ({
    flex: 1, padding: '8px', border: 'none', fontSize: '13px', fontWeight: 500,
    background: active ? C.cbRed : C.elevated,
    color: active ? '#fff' : C.muted,
    transition: 'all 0.15s', cursor: 'pointer',
  }),
  btnPrimary: {
    width: '100%', padding: '11px', borderRadius: '8px', border: 'none',
    background: C.cbRed, color: '#fff', fontSize: '14px', fontWeight: 600,
    letterSpacing: '-0.01em', cursor: 'pointer',
    transition: 'opacity 0.15s',
    boxShadow: '0 2px 8px rgba(234,35,40,0.4)',
  },
  btnSecondary: {
    width: '100%', padding: '11px', borderRadius: '8px',
    border: `1px solid ${C.border}`, background: 'transparent',
    color: C.muted, fontSize: '14px', cursor: 'pointer',
    marginTop: '10px', transition: 'color 0.15s',
  },
  errorBox: {
    padding: '10px 12px', borderRadius: '8px',
    background: 'rgba(248,113,113,0.1)', border: `1px solid rgba(248,113,113,0.3)`,
    color: C.red, fontSize: '13px', marginBottom: '16px', lineHeight: 1.5,
  },
  hint: {
    fontSize: '11.5px', color: C.faint, marginTop: '4px', lineHeight: 1.5,
  },
  divider: {
    borderTop: `1px solid ${C.border}`, margin: '0 24px',
  },
}

const PREFIXES = {
  server: 'couchbase://',
  capella: 'couchbases://',
}

export default function ConnectionScreen({ onConnect }) {
  const [step, setStep] = useState(1)
  const [clusterType, setClusterType] = useState('server')
  const [host, setHost] = useState('localhost')
  const [username, setUsername] = useState('Administrator')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [buckets, setBuckets] = useState([])
  const [scopes, setScopes] = useState([])
  const [collections, setCollections] = useState([])
  const [bucket, setBucket] = useState('')
  const [scope, setScope] = useState('')
  const [collection, setCollection] = useState('')
  const [loadingScopes, setLoadingScopes] = useState(false)
  const [loadingCols, setLoadingCols] = useState(false)

  const connectionString = PREFIXES[clusterType] + host

  useEffect(() => {
    if (clusterType === 'capella' && !host.includes('cloud.couchbase.com')) {
      setHost('cb.xxxxxxxx.cloud.couchbase.com')
    } else if (clusterType === 'server' && host.includes('cloud.couchbase.com')) {
      setHost('localhost')
    }
  }, [clusterType])

  const handleConnect = async () => {
    setError('')
    setLoading(true)
    try {
      const res = await api.connect({ connection_string: connectionString, username, password })
      setBuckets(res.buckets || [])
      if (res.buckets?.length) setBucket(res.buckets[0])
      setStep(2)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!bucket) return
    setScope('')
    setCollection('')
    setScopes([])
    setCollections([])
    setLoadingScopes(true)
    api.listScopes(bucket)
      .then(r => {
        const s = (r.scopes || []).filter(x => x !== '_system')
        setScopes(s)
        if (s.length) setScope(s[0])
      })
      .catch(() => {})
      .finally(() => setLoadingScopes(false))
  }, [bucket])

  useEffect(() => {
    if (!bucket || !scope) return
    setCollection('')
    setCollections([])
    setLoadingCols(true)
    api.listCollections(bucket, scope)
      .then(r => {
        setCollections(r.collections || [])
        if (r.collections?.length) setCollection(r.collections[0])
      })
      .catch(() => {})
      .finally(() => setLoadingCols(false))
  }, [bucket, scope])

  const handleBrowse = async () => {
    if (!bucket || !scope || !collection) return
    setError('')
    setLoading(true)
    try {
      await api.selectCollection(bucket, scope, collection)
      onConnect({
        connection_string: connectionString,
        bucket, scope, collection,
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={S.page}>
      <div style={S.logo}>
        <div style={S.logoMark}>
          <img src="/memman.png" alt="Memory Manager" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </div>
        <div>
          <div style={S.logoText}>Memory Manager</div>
          <div style={S.tagline}>Visualise and manage agent memories in Couchbase</div>
        </div>
      </div>

      <div style={S.card}>
        <div style={S.cardHeader}>
          <div style={S.stepRow}>
            <div style={S.stepDot(step === 1, step > 1)}>
              {step > 1 ? '✓' : '1'}
            </div>
            <span style={S.stepLabel(step === 1)}>Connect</span>
            <div style={S.stepLine} />
            <div style={S.stepDot(step === 2, false)}>2</div>
            <span style={S.stepLabel(step === 2)}>Select collection</span>
          </div>
        </div>

        <div style={S.divider} />

        <div style={S.cardBody}>
          {step === 1 ? (
            <>
              <div style={{ height: '20px' }} />

              <div style={S.toggleRow}>
                <button style={S.toggleBtn(clusterType === 'server')} onClick={() => setClusterType('server')}>
                  Couchbase Server
                </button>
                <button style={S.toggleBtn(clusterType === 'capella')} onClick={() => setClusterType('capella')}>
                  Capella (Cloud)
                </button>
              </div>

              <div style={S.fieldGroup}>
                <label style={S.label}>Host</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0' }}>
                  <span style={{
                    padding: '9px 10px', background: C.bg, border: `1px solid ${C.border}`,
                    borderRight: 'none', borderRadius: '8px 0 0 8px',
                    color: C.faint, fontSize: '12px', fontFamily: "'IBM Plex Mono', monospace",
                    whiteSpace: 'nowrap', flexShrink: 0,
                  }}>
                    {PREFIXES[clusterType]}
                  </span>
                  <input
                    value={host}
                    onChange={e => setHost(e.target.value)}
                    style={{ ...S.input, borderRadius: '0 8px 8px 0', borderLeft: 'none' }}
                    placeholder={clusterType === 'capella' ? 'cb.xxxxx.cloud.couchbase.com' : 'localhost'}
                    onKeyDown={e => e.key === 'Enter' && !loading && password && handleConnect()}
                  />
                </div>
                {clusterType === 'server' && (
                  <p style={S.hint}>
                    Running via Docker? Use <span style={{ fontFamily: "'IBM Plex Mono', monospace", color: C.muted }}>host.docker.internal</span> instead of <span style={{ fontFamily: "'IBM Plex Mono', monospace", color: C.muted }}>localhost</span> to reach a server on your machine.
                  </p>
                )}
                {clusterType === 'capella' && (
                  <p style={S.hint}>Ensure your IP address is on the Capella allowed list.</p>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={S.fieldGroup}>
                  <label style={S.label}>Username</label>
                  <input
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    style={S.input}
                    placeholder="Administrator"
                  />
                </div>
                <div style={S.fieldGroup}>
                  <label style={S.label}>Password</label>
                  <input
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    style={S.input}
                    placeholder="••••••••"
                    onKeyDown={e => e.key === 'Enter' && !loading && password && handleConnect()}
                  />
                </div>
              </div>

              {error && <div style={S.errorBox}>{error}</div>}

              <button
                style={{ ...S.btnPrimary, opacity: loading || !password ? 0.6 : 1 }}
                disabled={loading || !password}
                onClick={handleConnect}
              >
                {loading ? 'Connecting…' : 'Connect →'}
              </button>
            </>
          ) : (
            <>
              <div style={{ height: '20px' }} />

              <div style={{
                padding: '10px 12px', borderRadius: '8px', marginBottom: '20px',
                background: 'rgba(63, 185, 80, 0.1)', border: '1px solid rgba(63, 185, 80, 0.3)',
                fontSize: '12.5px', color: C.green, display: 'flex', alignItems: 'center', gap: '8px',
              }}>
                <span>●</span>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", color: C.muted }}>
                  {connectionString}
                </span>
              </div>

              <div style={S.fieldGroup}>
                <label style={S.label}>Bucket</label>
                <select
                  value={bucket}
                  onChange={e => setBucket(e.target.value)}
                  style={S.select}
                >
                  {buckets.map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </div>

              <div style={S.fieldGroup}>
                <label style={S.label}>Scope</label>
                <select
                  value={scope}
                  onChange={e => setScope(e.target.value)}
                  style={S.select}
                  disabled={loadingScopes || !scopes.length}
                >
                  {loadingScopes
                    ? <option>Loading…</option>
                    : scopes.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>

              <div style={S.fieldGroup}>
                <label style={S.label}>Collection</label>
                <select
                  value={collection}
                  onChange={e => setCollection(e.target.value)}
                  style={S.select}
                  disabled={loadingCols || !collections.length}
                >
                  {loadingCols
                    ? <option>Loading…</option>
                    : collections.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>

              {error && <div style={S.errorBox}>{error}</div>}

              <button
                style={{ ...S.btnPrimary, opacity: loading || !bucket || !scope || !collection ? 0.6 : 1 }}
                disabled={loading || !bucket || !scope || !collection}
                onClick={handleBrowse}
              >
                {loading ? 'Opening…' : 'Browse Memories →'}
              </button>
              <button
                style={S.btnSecondary}
                onClick={() => { setStep(1); setError('') }}
              >
                ← Back
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
