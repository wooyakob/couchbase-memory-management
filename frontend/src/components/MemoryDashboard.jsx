import { useState, useEffect, useCallback, useMemo } from 'react'
import { api } from '../api'

// ─── DESIGN TOKENS ───────────────────────────────────────────────────────────
const C = {
  bg: '#0d1117', surface: '#161b22', elevated: '#1c2333', hover: '#1e2636',
  border: '#30363d', borderActive: '#388bfd',
  text: '#e6edf3', textMid: '#c9d1d9', muted: '#8b949e', faint: '#6e7681',
  blue: '#58a6ff', cbRed: '#EA2328', green: '#3fb950',
  red: '#f87171', yellow: '#e3b341', orange: '#f0883e',
}

const THEME_COLORS = ['#60a5fa','#34d399','#a78bfa','#fbbf24','#f87171','#22d3ee','#fb923c','#e879f9']
const TYPE_COLORS = { preference: '#60a5fa', trip: '#34d399', memory: '#a78bfa', fact: '#fbbf24', event: '#22d3ee' }

// ─── HELPERS ─────────────────────────────────────────────────────────────────
const mono = "'IBM Plex Mono', 'Courier New', monospace"
const display = "'Space Grotesk', system-ui, sans-serif"

function shortId(id = '') { return id.length > 14 ? id.slice(0, 12) + '…' : id }
function fmtDate(iso) {
  if (!iso) return ''
  try { return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) }
  catch { return iso.slice(0, 10) }
}
function fmtExpiry(val) {
  if (!val || val === 0) return 'None (no expiry)'
  try {
    const d = new Date(val * 1000)
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return String(val) }
}

function getPrimaryText(doc) {
  return doc.summary || doc.content || doc.fact || doc.text || doc.message?.user_content || ''
}
function getTimestamp(doc) {
  return doc.ingested_at || doc.updated_at || doc.booked_at || doc.created_at || doc.start_time || ''
}
function typeColor(t) { return TYPE_COLORS[t] || C.blue }

const META_FIELDS = new Set(['__cb_key', '__cb_cas', '__cb_expiry', '__cb_doc_type'])
const EMBEDDING_FIELD_NAMES = new Set(['embedding', 'embeddings', 'vector', 'vectors', '$vector', 'embedding_vector', 'vec'])

function isEmbeddingField(key, val) {
  if (EMBEDDING_FIELD_NAMES.has(key.toLowerCase())) return true
  return Array.isArray(val) && val.length > 20 && val.every(v => typeof v === 'number')
}
function isMetaField(key) { return META_FIELDS.has(key) }

function statusBadgeStyle(status) {
  if (!status) return {}
  const isOk = ['ready', 'active', 'done'].includes(status)
  const isErr = ['failed', 'extraction_failed', 'error'].includes(status)
  return {
    fontSize: '10px', fontFamily: mono, padding: '1px 7px', borderRadius: '10px',
    background: isErr ? 'rgba(248,113,113,.12)' : isOk ? 'rgba(63,185,80,.12)' : 'rgba(227,179,65,.12)',
    color: isErr ? C.red : isOk ? C.green : C.yellow,
    border: `1px solid ${isErr ? 'rgba(248,113,113,.3)' : isOk ? 'rgba(63,185,80,.3)' : 'rgba(227,179,65,.3)'}`,
  }
}

// ─── COPY BUTTON ─────────────────────────────────────────────────────────────
function CopyBtn({ value, style = {} }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = (e) => {
    e.stopPropagation()
    const finish = () => { setCopied(true); setTimeout(() => setCopied(false), 1400) }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value).then(finish).catch(() => {
        // Clipboard API unavailable (non-HTTPS or permission denied) — fall back to execCommand
        try {
          const el = document.createElement('textarea')
          el.value = value
          el.style.position = 'fixed'; el.style.opacity = '0'
          document.body.appendChild(el); el.select()
          document.execCommand('copy')
          document.body.removeChild(el)
          finish()
        } catch { /* silently ignore if both methods fail */ }
      })
    } else {
      try {
        const el = document.createElement('textarea')
        el.value = value
        el.style.position = 'fixed'; el.style.opacity = '0'
        document.body.appendChild(el); el.select()
        document.execCommand('copy')
        document.body.removeChild(el)
        finish()
      } catch { /* silently ignore */ }
    }
  }
  return (
    <button
      title="Copy Block ID"
      onClick={handleCopy}
      style={{
        background: 'none', border: 'none', cursor: 'pointer',
        padding: '1px 5px', borderRadius: '4px',
        color: copied ? C.green : C.faint,
        fontSize: '11px', fontFamily: mono,
        transition: 'color 0.15s',
        flexShrink: 0,
        ...style,
      }}
    >
      {copied ? '✓' : '⧉'}
    </button>
  )
}

// ─── TOAST ───────────────────────────────────────────────────────────────────
function Toast({ msg, type }) {
  return (
    <div style={{
      position: 'fixed', bottom: '24px', right: '24px', zIndex: 300,
      padding: '10px 16px', borderRadius: '8px', fontSize: '13px',
      background: type === 'error' ? '#2d1a1a' : '#0f2d1a',
      border: `1px solid ${type === 'error' ? 'rgba(248,113,113,.4)' : 'rgba(63,185,80,.4)'}`,
      color: type === 'error' ? C.red : C.green,
      boxShadow: '0 4px 16px rgba(0,0,0,.5)', pointerEvents: 'none',
      fontWeight: 500,
    }}>{msg}</div>
  )
}

// ─── SIDEBAR ─────────────────────────────────────────────────────────────────
function Sidebar({ total, filtered, groups, themes, activeFilter, timeRange, onFilter, onSearch, onTimeRange, onAutoCluster, clustering }) {
  const NavBtn = ({ id, label, count, color }) => {
    const active = activeFilter?.key === id || (!activeFilter && id === '__all__')
    return (
      <button onClick={() => onFilter(id === '__all__' ? null : { key: id, label })} title={label} style={{
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px',
        width: '100%', padding: '6px 14px', border: 'none', textAlign: 'left',
        borderLeft: `2px solid ${active ? C.cbRed : 'transparent'}`,
        background: active ? 'rgba(234,35,40,0.08)' : 'transparent',
        color: active ? C.text : C.muted, fontSize: '12.5px', cursor: 'pointer',
        transition: 'all 0.12s',
      }}>
        <span style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', minWidth: 0, flex: 1 }}>
          {color && <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: color, flexShrink: 0, marginTop: '5px' }} />}
          <span style={{ minWidth: 0, overflowWrap: 'anywhere', wordBreak: 'break-word', lineHeight: 1.35 }}>{label}</span>
        </span>
        <span style={{ fontFamily: mono, fontSize: '10px', background: C.elevated, padding: '1px 6px', borderRadius: '8px', flexShrink: 0, marginTop: '1px' }}>
          {count}
        </span>
      </button>
    )
  }

  const SectionHead = ({ label }) => (
    <div style={{ padding: '12px 14px 4px', fontFamily: mono, fontSize: '10px', color: C.faint, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
      {label}
    </div>
  )

  const TIME_OPTS = [
    { value: null, label: 'All' },
    { value: 'hour', label: '1h' },
    { value: 'day', label: '24h' },
    { value: 'week', label: '7d' },
  ]

  return (
    <aside style={{ width: '220px', background: C.surface, borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column', flexShrink: 0, overflowY: 'auto' }}>
      <div style={{ padding: '12px 10px 4px' }}>
        <div style={{ position: 'relative' }}>
          <span style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: C.faint, fontSize: '13px', pointerEvents: 'none' }}>⌕</span>
          <input
            placeholder="Search or paste a Block ID…"
            style={{
              width: '100%', padding: '7px 10px 7px 28px',
              background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '6px',
              color: C.text, fontSize: '12.5px', outline: 'none', boxSizing: 'border-box',
            }}
            onChange={e => onSearch(e.target.value)}
          />
        </div>
        <div style={{ fontFamily: mono, fontSize: '10px', color: C.faint, marginTop: '5px', paddingLeft: '2px', lineHeight: 1.5 }}>
          Paste a full Block ID for exact match
        </div>
      </div>

      {/* Time Range */}
      <SectionHead label="Time Window" />
      <div style={{ padding: '0 10px 8px', display: 'flex', gap: '4px' }}>
        {TIME_OPTS.map(({ value, label }) => {
          const active = timeRange === value
          return (
            <button
              key={label}
              onClick={() => onTimeRange(value)}
              style={{
                flex: 1, padding: '5px 0', borderRadius: '5px',
                border: `1px solid ${active ? C.cbRed : C.border}`,
                background: active ? 'rgba(234,35,40,0.1)' : C.elevated,
                color: active ? C.cbRed : C.muted,
                fontSize: '11px', cursor: 'pointer', fontFamily: mono,
                transition: 'all 0.12s',
              }}
            >{label}</button>
          )
        })}
      </div>

      <NavBtn id="__all__" label="All memories" count={total} />

      {groups.type?.length > 0 && (
        <>
          <SectionHead label="Type" />
          {groups.type.map(t => <NavBtn key={t} id={`type:${t}`} label={t} count="?" color={typeColor(t)} />)}
        </>
      )}

      {groups.user_id?.length > 0 && (
        <>
          <SectionHead label="User" />
          {groups.user_id.map(u => <NavBtn key={u} id={`user:${u}`} label={u} count="?" color={C.muted} />)}
        </>
      )}

      {Object.keys(themes).length > 0 && (
        <>
          <SectionHead label="Groups (AI)" />
          {Object.entries(themes).map(([name, ids], i) => (
            <NavBtn key={name} id={`theme:${name}`} label={name} count={ids.length} color={THEME_COLORS[i % THEME_COLORS.length]} />
          ))}
        </>
      )}

      <div style={{ marginTop: 'auto', padding: '12px 10px', borderTop: `1px solid ${C.border}` }}>
        <button
          onClick={onAutoCluster}
          disabled={clustering}
          style={{
            width: '100%', padding: '7px', borderRadius: '7px',
            border: `1px solid ${C.border}`, background: C.elevated,
            color: clustering ? C.faint : C.blue, fontSize: '12px', cursor: clustering ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
          }}
        >
          <span>✦</span> {clustering ? 'Grouping…' : 'Auto Group Memories'}
        </button>
        <div style={{ fontFamily: mono, fontSize: '10px', color: C.faint, marginTop: '8px', textAlign: 'center' }}>
          {filtered} shown of {total}
        </div>
      </div>
    </aside>
  )
}

// ─── MEMORY CARD ─────────────────────────────────────────────────────────────
function MemoryCard({ doc, selected, theme, onSelect, onDelete }) {
  const docId = doc.__cb_key || '—'
  const primary = getPrimaryText(doc)
  const ts = getTimestamp(doc)
  const contexts = Array.isArray(doc.contexts) ? doc.contexts : []

  return (
    <div
      onClick={() => onSelect(docId)}
      style={{
        background: selected ? C.elevated : C.surface,
        border: `1px solid ${selected ? C.borderActive : C.border}`,
        borderRadius: '10px', padding: '14px', cursor: 'pointer',
        transition: 'border-color 0.12s, background 0.12s',
        borderLeft: theme ? `3px solid ${theme}` : `1px solid ${selected ? C.borderActive : C.border}`,
      }}
    >
      {/* Top row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '2px', minWidth: 0 }}>
          <span style={{ fontFamily: mono, fontSize: '11px', color: C.faint, whiteSpace: 'nowrap' }}>{shortId(docId)}</span>
          <CopyBtn value={docId} />
        </div>
        <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap', justifyContent: 'flex-end', flexShrink: 0 }}>
          {doc.type && (
            <span style={{ fontSize: '10px', padding: '1px 7px', borderRadius: '10px', background: `${typeColor(doc.type)}18`, color: typeColor(doc.type), border: `1px solid ${typeColor(doc.type)}30`, fontWeight: 500 }}>
              {doc.type}
            </span>
          )}
          {doc.status && <span style={statusBadgeStyle(doc.status)}>{doc.status}</span>}
        </div>
      </div>

      {/* Primary content */}
      {primary ? (
        <p style={{ fontSize: '13px', lineHeight: 1.5, color: C.textMid, margin: '0 0 10px', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {primary}
        </p>
      ) : (
        <p style={{ fontSize: '12px', color: C.faint, margin: '0 0 10px', fontStyle: 'italic' }}>No summary — {Object.entries(doc).filter(([k, v]) => !isMetaField(k) && !isEmbeddingField(k, v)).length} fields</p>
      )}

      {/* Context chips */}
      {contexts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '10px' }}>
          {contexts.slice(0, 3).map((c, i) => (
            <span key={i} style={{ fontSize: '11px', padding: '2px 8px', background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '4px', color: C.muted, lineHeight: 1.4 }}>
              {String(c).length > 40 ? String(c).slice(0, 40) + '…' : String(c)}
            </span>
          ))}
          {contexts.length > 3 && <span style={{ fontSize: '11px', padding: '2px 8px', background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '4px', color: C.faint }}>+{contexts.length - 3}</span>}
        </div>
      )}

      {/* Category chip for preference-style docs */}
      {doc.category && !contexts.length && (
        <div style={{ marginBottom: '10px' }}>
          <span style={{ fontSize: '11px', padding: '2px 8px', background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '4px', color: C.muted }}>
            {doc.category}
          </span>
        </div>
      )}

      {/* Footer */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: `1px solid ${C.border}`, paddingTop: '9px' }}>
        <div style={{ fontFamily: mono, fontSize: '10px', color: C.faint, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {doc.user_id && <span style={{ marginRight: '6px' }}>{doc.user_id}</span>}
          {ts && fmtDate(ts)}
          {doc.tokens && <span style={{ marginLeft: '6px' }}>{doc.tokens} tok</span>}
        </div>
        <div style={{ display: 'flex', gap: '4px' }} onClick={e => e.stopPropagation()}>
          <button
            onClick={() => onDelete(docId)}
            style={{ padding: '2px 9px', background: 'transparent', border: `1px solid ${C.border}`, borderRadius: '5px', color: C.red, fontSize: '11px', cursor: 'pointer' }}
          >Delete</button>
        </div>
      </div>
    </div>
  )
}

// ─── DETAIL PANEL ─────────────────────────────────────────────────────────────
function DetailPanel({ doc, onClose, onDelete }) {
  const [activeTab, setActiveTab] = useState('document')
  const docId = doc.__cb_key || '—'

  const documentFields = Object.entries(doc).filter(([k, v]) => !isMetaField(k) && !isEmbeddingField(k, v))
  const embeddingFields = Object.entries(doc).filter(([k, v]) => !isMetaField(k) && isEmbeddingField(k, v))
  const hasEmbedding = embeddingFields.length > 0

  const renderValue = (val) => {
    if (Array.isArray(val)) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {val.map((v, i) => (
            <div key={i} style={{ padding: '5px 9px', background: C.bg, border: `1px solid ${C.border}`, borderRadius: '5px', fontSize: '12px', color: C.muted }}>
              {String(v)}
            </div>
          ))}
        </div>
      )
    }
    if (typeof val === 'object' && val !== null) {
      return <pre style={{ fontFamily: mono, fontSize: '11px', color: C.muted, background: C.bg, border: `1px solid ${C.border}`, borderRadius: '6px', padding: '8px', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(val, null, 2)}</pre>
    }
    if (typeof val === 'boolean') {
      return <span style={{ ...statusBadgeStyle(val ? 'ready' : 'failed'), display: 'inline-block' }}>{String(val)}</span>
    }
    return <span style={{ fontSize: '13px', color: C.textMid }}>{String(val)}</span>
  }

  const Label = ({ children }) => (
    <div style={{ fontFamily: mono, fontSize: '10px', color: C.faint, textTransform: 'uppercase', letterSpacing: '0.8px', marginBottom: '5px' }}>
      {children}
    </div>
  )

  const Tab = ({ id, label }) => (
    <button
      onClick={() => setActiveTab(id)}
      style={{
        flex: 1, padding: '8px 0', border: 'none', background: 'none',
        borderBottom: `2px solid ${activeTab === id ? C.cbRed : 'transparent'}`,
        color: activeTab === id ? C.text : C.muted,
        fontSize: '12px', fontWeight: activeTab === id ? 600 : 400,
        cursor: 'pointer', transition: 'all 0.12s',
      }}
    >{label}</button>
  )

  return (
    <div style={{ width: '340px', background: C.surface, borderLeft: `1px solid ${C.border}`, overflowY: 'auto', flexShrink: 0, display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ padding: '16px 16px 0', borderBottom: `1px solid ${C.border}`, position: 'sticky', top: 0, background: C.surface, zIndex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <span style={{ fontFamily: mono, fontSize: '12px', color: C.blue }}>Document</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.muted, fontSize: '18px', lineHeight: 1, cursor: 'pointer', padding: '2px 4px' }}>×</button>
        </div>
        <div style={{ display: 'flex' }}>
          <Tab id="document" label="Document" />
          <Tab id="metadata" label="Metadata" />
        </div>
      </div>

      <div style={{ padding: '14px 16px', flex: 1 }}>
        {activeTab === 'document' ? (
          <>
            {documentFields.map(([k, v]) => (
              <div key={k} style={{ marginBottom: '14px' }}>
                <Label>{k}</Label>
                {k === 'block_id' && typeof v === 'string' ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <div style={{ flex: 1 }}>{renderValue(v)}</div>
                    <CopyBtn value={v} style={{ fontSize: '14px', padding: '4px 7px', flexShrink: 0 }} />
                  </div>
                ) : renderValue(v)}
              </div>
            ))}
            {documentFields.length === 0 && (
              <div style={{ fontFamily: mono, fontSize: '12px', color: C.faint, textAlign: 'center', padding: '32px 0' }}>
                No document fields
              </div>
            )}
          </>
        ) : (
          <>
            <div style={{ marginBottom: '14px' }}>
              <Label>Document Key (Block ID)</Label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <div style={{
                  fontFamily: mono, fontSize: '11px', color: C.blue,
                  background: C.elevated, padding: '6px 8px', borderRadius: '6px',
                  wordBreak: 'break-all', lineHeight: 1.6, flex: 1,
                }}>
                  {docId}
                </div>
                <CopyBtn value={docId} style={{ fontSize: '14px', padding: '4px 7px' }} />
              </div>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <Label>CAS (Compare-and-Swap)</Label>
              <div style={{
                fontFamily: mono, fontSize: '11px', color: C.muted,
                background: C.elevated, padding: '6px 8px', borderRadius: '6px',
                wordBreak: 'break-all', lineHeight: 1.6,
              }}>
                {doc.__cb_cas != null ? String(doc.__cb_cas) : '—'}
              </div>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <Label>Expiry</Label>
              <div style={{ fontSize: '13px', color: doc.__cb_expiry ? C.yellow : C.green }}>
                {fmtExpiry(doc.__cb_expiry)}
              </div>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <Label>Document Type</Label>
              <span style={{ fontFamily: mono, fontSize: '11px', color: C.muted, background: C.elevated, padding: '3px 8px', borderRadius: '4px' }}>
                {doc.__cb_doc_type || 'json'}
              </span>
            </div>

            <div style={{ height: '1px', background: C.border, margin: '16px 0' }} />

            <div style={{ marginBottom: '14px' }}>
              <Label>Field Count</Label>
              <div style={{ fontSize: '13px', color: C.textMid }}>
                {documentFields.length} field{documentFields.length !== 1 ? 's' : ''}
              </div>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <Label>Embedding</Label>
              {hasEmbedding ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {embeddingFields.map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontFamily: mono, fontSize: '11px', color: C.green, background: 'rgba(63,185,80,.1)', border: '1px solid rgba(63,185,80,.25)', padding: '2px 8px', borderRadius: '4px' }}>
                        {k}
                      </span>
                      <span style={{ fontSize: '11px', color: C.faint }}>{v.length} dimensions</span>
                    </div>
                  ))}
                </div>
              ) : (
                <span style={{ fontSize: '13px', color: C.faint }}>None</span>
              )}
            </div>
          </>
        )}
      </div>

      {/* Actions */}
      <div style={{ padding: '12px 16px', borderTop: `1px solid ${C.border}`, position: 'sticky', bottom: 0, background: C.surface }}>
        <button
          onClick={() => onDelete(docId)}
          style={{ width: '100%', padding: '8px 14px', borderRadius: '7px', border: `1px solid rgba(248,113,113,.3)`, background: 'rgba(248,113,113,.06)', color: C.red, fontSize: '13px', cursor: 'pointer', fontWeight: 500 }}
        >Delete Memory</button>
      </div>
    </div>
  )
}

// ─── DELETE CONFIRM ───────────────────────────────────────────────────────────
function DeleteConfirm({ docId, onClose, onConfirm }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: '24px' }}>
      <div style={{ background: C.surface, border: '1px solid rgba(248,113,113,.3)', borderRadius: '14px', width: '100%', maxWidth: '380px', padding: '24px', boxShadow: '0 16px 48px rgba(0,0,0,.6)' }}>
        <div style={{ fontSize: '16px', fontWeight: 600, color: C.text, marginBottom: '8px', fontFamily: display }}>Delete this memory?</div>
        <p style={{ fontSize: '13px', color: C.muted, marginBottom: '20px', lineHeight: 1.6 }}>
          Document <span style={{ fontFamily: mono, color: C.red }}>{shortId(docId)}</span> will be permanently removed from Couchbase. This cannot be undone.
        </p>
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 16px', borderRadius: '7px', border: `1px solid ${C.border}`, background: 'transparent', color: C.muted, fontSize: '13px', cursor: 'pointer' }}>Cancel</button>
          <button onClick={onConfirm} style={{ padding: '8px 18px', borderRadius: '7px', border: 'none', background: '#c42b2b', color: '#fff', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}>Delete</button>
        </div>
      </div>
    </div>
  )
}

// ─── AUTO GROUP MODAL ─────────────────────────────────────────────────────────
const CLUSTER_PROVIDERS = [
  { id: 'capella', label: 'Capella Model Service', placeholder: 'Bearer token / API key', model: '' },
  { id: 'anthropic', label: 'Claude', placeholder: 'sk-ant-…', model: 'claude-haiku-4-5-20251001' },
  { id: 'openai', label: 'OpenAI', placeholder: 'sk-…', model: 'gpt-4o-mini' },
  { id: 'gemini', label: 'Gemini', placeholder: 'AIza…', model: 'gemini-2.5-flash' },
]

const CLUSTER_PROMPT = (payload) =>
  `Cluster these memory documents into 3–7 concise themes (2-3 words each). Return ONLY valid JSON — no markdown: {"themes":{"Theme Name":["doc_id"],...}}\n\nDocuments: ${JSON.stringify(payload)}`

async function callClusterAPI(provider, apiKey, prompt, endpoint, model) {
  if (provider === 'capella') {
    let base
    try {
      base = new URL(endpoint.replace(/\/$/, '')).href.replace(/\/$/, '')
    } catch {
      throw new Error('Invalid endpoint URL. It should look like: https://your-model.ai.couchbase.com')
    }
    // Proxy through the backend to avoid CORS restrictions
    const res = await fetch('/api/cluster', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: base, api_key: apiKey, model: model || '', prompt }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || `Capella Model Service error (HTTP ${res.status})`)
    if (!data.text) throw new Error('Capella Model Service returned an empty response.')
    return data.text
  }
  if (provider === 'anthropic') {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 4096, messages: [{ role: 'user', content: prompt }] }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error?.message || 'Anthropic API error')
    return (data.content || []).map(b => b.text || '').join('')
  }
  if (provider === 'openai') {
    const res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
      body: JSON.stringify({ model: 'gpt-4o-mini', max_tokens: 4096, messages: [{ role: 'user', content: prompt }] }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error?.message || 'OpenAI API error')
    return data.choices?.[0]?.message?.content || ''
  }
  if (provider === 'gemini') {
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${apiKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error?.message || 'Gemini API error')
    return data.candidates?.[0]?.content?.parts?.[0]?.text || ''
  }
  throw new Error('Unknown provider')
}

function ClusterModal({ filterParams, onClose, onApply }) {
  const [provider, setProvider] = useState('capella')
  const [apiKey, setApiKey] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [modelName, setModelName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const providerMeta = CLUSTER_PROVIDERS.find(p => p.id === provider)
  const canRun = provider === 'capella' ? (apiKey && endpoint) : !!apiKey

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      // Group ALL memories in the current view (typically one user), not just
      // the page on screen — fetch a lightweight id + text projection for the
      // whole filtered set (capped server-side, most-recent-first).
      const input = await api.getClusterInput(filterParams)
      const source = input.documents || []
      // Use numeric indices as IDs — models reliably reproduce small integers,
      // unlike long UUIDs which get mangled. Map back to the real key after.
      const eligible = source.filter(m => getPrimaryText(m))
      if (!eligible.length) throw new Error('No memories with text to group in the current view.')
      const indexToKey = eligible.map(m => m.id)
      const payload = eligible.map((m, i) => ({ id: String(i), text: getPrimaryText(m) }))
      const raw = await callClusterAPI(provider, apiKey, CLUSTER_PROMPT(payload), endpoint, modelName)
      const match = raw.match(/\{[\s\S]*\}/)
      if (!match) throw new Error('No JSON returned by the model')
      const parsed = JSON.parse(match[0])
      // Translate numeric indices back to actual Couchbase document keys
      const resolved = {}
      Object.entries(parsed.themes || {}).forEach(([theme, ids]) => {
        resolved[theme] = ids.map(id => indexToKey[Number(id)]).filter(Boolean)
      })
      onApply(resolved, { total: input.total, considered: eligible.length, truncated: input.truncated })
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: '24px' }}>
      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: '14px', width: '100%', maxWidth: '480px', padding: '24px', boxShadow: '0 16px 48px rgba(0,0,0,.6)' }}>
        <div style={{ fontSize: '16px', fontWeight: 600, color: C.text, marginBottom: '6px', fontFamily: display }}>Auto Group Memories</div>
        <p style={{ fontSize: '13px', color: C.muted, marginBottom: '18px', lineHeight: 1.6 }}>
          Groups {filterParams?.user_id
            ? <>the memories for user <strong style={{ color: C.text }}>{filterParams.user_id}</strong></>
            : filterParams?.type
              ? <>the memories of type <strong style={{ color: C.text }}>{filterParams.type}</strong></>
              : 'all memories in the current view'} (up to 500 most recent) into themes using an LLM.
          Your API key is used directly from the browser and never stored.
        </p>

        {/* Provider tabs */}
        <div style={{ display: 'flex', gap: '6px', marginBottom: '16px', background: C.bg, borderRadius: '9px', padding: '4px', overflowX: 'auto' }}>
          {CLUSTER_PROVIDERS.map(p => (
            <button
              key={p.id}
              onClick={() => { setProvider(p.id); setApiKey(''); setEndpoint(''); setModelName(''); setError('') }}
              style={{
                flex: '0 0 auto', padding: '6px 10px', borderRadius: '6px', border: 'none', fontSize: '12px', fontWeight: 500, cursor: 'pointer',
                background: provider === p.id ? C.elevated : 'transparent',
                color: provider === p.id ? C.text : C.muted,
                boxShadow: provider === p.id ? `0 0 0 1px ${C.border}` : 'none',
                transition: 'all 0.12s', whiteSpace: 'nowrap',
              }}
            >{p.label}</button>
          ))}
        </div>

        {/* Capella badges */}
        {provider === 'capella' && (
          <div style={{ marginBottom: '14px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{ fontSize: '11px', padding: '2px 9px', borderRadius: '10px', background: 'rgba(63,185,80,.1)', color: C.green, border: '1px solid rgba(63,185,80,.25)', fontWeight: 500 }}>
              Most secure
            </span>
            <span style={{ fontSize: '11px', padding: '2px 9px', borderRadius: '10px', background: 'rgba(63,185,80,.1)', color: C.green, border: '1px solid rgba(63,185,80,.25)', fontWeight: 500 }}>
              Cost effective
            </span>
            <span style={{ fontSize: '11px', padding: '2px 9px', borderRadius: '10px', background: 'rgba(88,166,255,.08)', color: C.muted, border: `1px solid ${C.border}` }}>
              LLM only — not for embeddings
            </span>
          </div>
        )}

        {/* Capella endpoint + model fields */}
        {provider === 'capella' && (
          <>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: C.muted, marginBottom: '6px' }}>
                Model Endpoint URL
              </label>
              <input
                type="text"
                value={endpoint}
                onChange={e => setEndpoint(e.target.value)}
                placeholder="https://your-model.ai.couchbase.com"
                style={{ width: '100%', padding: '9px 12px', background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '8px', color: C.text, fontSize: '13px', outline: 'none', fontFamily: mono, boxSizing: 'border-box' }}
              />
              <div style={{ fontFamily: mono, fontSize: '10px', color: C.faint, marginTop: '4px' }}>
                From Capella AI &rsaquo; Model Service &rsaquo; your deployed model endpoint
              </div>
            </div>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: C.muted, marginBottom: '6px' }}>
                Model Name
              </label>
              <input
                type="text"
                value={modelName}
                onChange={e => setModelName(e.target.value)}
                placeholder="mistralai/mistral-7b-instruct-v0.3"
                style={{ width: '100%', padding: '9px 12px', background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '8px', color: C.text, fontSize: '13px', outline: 'none', fontFamily: mono, boxSizing: 'border-box' }}
              />
              <div style={{ fontFamily: mono, fontSize: '10px', color: C.faint, marginTop: '4px' }}>
                From Capella AI &rsaquo; Model Service &rsaquo; your deployed model name
              </div>
            </div>
          </>
        )}

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: C.muted, marginBottom: '6px' }}>
            {providerMeta.label} API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder={providerMeta.placeholder}
            style={{ width: '100%', padding: '9px 12px', background: C.elevated, border: `1px solid ${C.border}`, borderRadius: '8px', color: C.text, fontSize: '13px', outline: 'none', fontFamily: mono, boxSizing: 'border-box' }}
          />
        </div>

        {error && <div style={{ fontSize: '12px', color: C.red, marginBottom: '12px' }}>{error}</div>}
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 16px', borderRadius: '7px', border: `1px solid ${C.border}`, background: 'transparent', color: C.muted, fontSize: '13px', cursor: 'pointer' }}>Cancel</button>
          <button
            onClick={run}
            disabled={!canRun || busy}
            style={{ padding: '8px 18px', borderRadius: '7px', border: 'none', background: C.blue, color: '#fff', fontSize: '13px', fontWeight: 600, cursor: !canRun || busy ? 'not-allowed' : 'pointer', opacity: !canRun || busy ? 0.6 : 1 }}
          >
            {busy ? 'Grouping…' : '✦ Group'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── MAIN DASHBOARD ───────────────────────────────────────────────────────────
export default function MemoryDashboard({ connection, onDisconnect }) {
  const { bucket, scope, collection, connection_string } = connection

  const [docs, setDocs] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const LIMIT = 50

  const [loading, setLoading] = useState(false)
  const [noIndex, setNoIndex] = useState(false)
  const [creatingIndex, setCreatingIndex] = useState(false)

  const [groups, setGroups] = useState({})
  const [themes, setThemes] = useState({})
  const [activeFilter, setActiveFilter] = useState(null)
  const [searchVal, setSearchVal] = useState('')
  const [timeRange, setTimeRange] = useState(null)

  const [selectedId, setSelectedId] = useState(null)
  const [deleteId, setDeleteId] = useState(null)
  const [showCluster, setShowCluster] = useState(false)
  const [clustering, setClustering] = useState(false)

  const [toast, setToast] = useState(null)

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 2800)
  }

  const queryParams = useCallback(() => {
    const params = { limit: LIMIT, offset }
    if (searchVal) params.search = searchVal
    if (timeRange) params.time_range = timeRange
    if (!activeFilter) return params
    if (activeFilter.key.startsWith('type:')) return { ...params, type: activeFilter.key.slice(5) }
    if (activeFilter.key.startsWith('user:')) return { ...params, user_id: activeFilter.key.slice(5) }
    return params
  }, [activeFilter, offset, searchVal, timeRange])

  const fetchDocs = useCallback(async (retry = 0) => {
    setLoading(true)
    setNoIndex(false)
    try {
      if (activeFilter?.key?.startsWith('theme:')) {
        // AI groups can span more memories than one browse page, so page
        // through the group's member ids and fetch just this page's full
        // documents by key rather than re-querying the whole collection.
        const name = activeFilter.key.slice(6)
        const ids = themes[name] || []
        const pageIds = ids.slice(offset, offset + LIMIT)
        const res = pageIds.length ? await api.getDocumentsByIds(pageIds) : { documents: [] }
        const byKey = new Map((res.documents || []).map(d => [d.__cb_key, d]))
        setDocs(pageIds.map(id => byKey.get(id)).filter(Boolean))
        setTotal(ids.length)
        return
      }
      const params = queryParams()
      const res = await api.listMemories(params)
      setDocs(res.documents || [])
      setTotal(res.total || 0)
    } catch (e) {
      if (e.detail === 'no_index' || (e.message || '').includes('no_index')) {
        // Backend already tried to auto-create the recommended indexes and
        // couldn't (e.g. the credential can't manage indexes) — fall back
        // to the manual "Create Secondary Indexes" button.
        setNoIndex(true)
        setDocs([])
      } else if (e.status === 503 && retry < 5) {
        // Indexes were just created and are still coming online — the
        // backend already retried once; keep polling here instead of
        // surfacing an error the user would have to act on.
        setTimeout(() => fetchDocs(retry + 1), 3000)
      } else {
        showToast(e.message, 'error')
      }
    } finally {
      setLoading(false)
    }
  }, [queryParams, activeFilter, themes, offset])

  useEffect(() => { fetchDocs() }, [fetchDocs])

  useEffect(() => {
    api.getGroups().then(setGroups).catch(() => {})
  }, [])

  const handleCreateIndex = async () => {
    setCreatingIndex(true)
    try {
      await api.createIndex()
      setNoIndex(false)
      showToast('Secondary indexes created')
      fetchDocs()
      api.getGroups().then(setGroups).catch(() => {})
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      setCreatingIndex(false)
    }
  }

  const handleFilter = (filter) => {
    // AI groups are computed for one specific scope (e.g. a single user), so
    // they're stale and misleading once you switch to a different user/type/all
    // scope — clear them. Navigating INTO a theme must keep them, though.
    if (!filter?.key?.startsWith('theme:')) setThemes({})
    setActiveFilter(filter)
    setOffset(0)
    setSelectedId(null)
  }

  const handleSearch = (val) => {
    setSearchVal(val)
    setThemes({})
    setOffset(0)
    setSelectedId(null)
  }

  const handleTimeRange = (val) => {
    setTimeRange(val)
    setThemes({})
    setOffset(0)
    setSelectedId(null)
  }

  const handleDelete = async () => {
    try {
      await api.deleteMemory(deleteId)
      showToast('Memory deleted')
      setDocs(prev => prev.filter(d => d.__cb_key !== deleteId))
      setTotal(t => t - 1)
      if (selectedId === deleteId) setSelectedId(null)
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      setDeleteId(null)
    }
  }

  const handleApplyThemes = (newThemes, meta) => {
    setThemes(newThemes)
    // Land on a clean "all memories" view — the new groups are in the sidebar,
    // and any previously-selected group name may no longer exist.
    setActiveFilter(null)
    setOffset(0)
    const n = Object.keys(newThemes).length
    const note = meta?.truncated ? ` — grouped ${meta.considered} most recent of ${meta.total}` : ''
    showToast(`Grouped into ${n} theme${n !== 1 ? 's' : ''}${note}`)
  }

  // Reverse index: which group each memory belongs to, spanning every page.
  const idToTheme = useMemo(() => {
    const m = {}
    Object.entries(themes).forEach(([name, ids]) => ids.forEach(id => { m[id] = name }))
    return m
  }, [themes])

  const selectedDoc = selectedId ? docs.find(d => d.__cb_key === selectedId) : null

  // Server (or by-ids for a group) already returns exactly the page to show.
  const visibleDocs = docs

  // Filters that scope Auto Group to the current view (e.g. one user), so
  // grouping runs over that whole set rather than the visible page. A group
  // filter isn't a server-side filter, so it's excluded here.
  const clusterParams = () => {
    const p = {}
    if (searchVal) p.search = searchVal
    if (timeRange) p.time_range = timeRange
    if (activeFilter?.key?.startsWith('type:')) p.type = activeFilter.key.slice(5)
    if (activeFilter?.key?.startsWith('user:')) p.user_id = activeFilter.key.slice(5)
    return p
  }

  const isCapella = connection_string?.startsWith('couchbases://')

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: C.bg }}>
      {/* Header */}
      <header style={{
        background: C.surface, borderBottom: `1px solid ${C.border}`,
        padding: '0 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: '52px', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <img src="/memman.png" alt="Memory Manager" style={{ width: '24px', height: '24px', borderRadius: '5px', objectFit: 'cover' }} />
            <span style={{ fontFamily: display, fontWeight: 700, fontSize: '14px', color: C.text }}>Memory Manager</span>
          </div>
          <span style={{ color: C.faint, fontSize: '13px' }}>/</span>
          <span style={{ fontFamily: mono, fontSize: '12px', color: C.muted }}>
            {bucket} · {scope} · {collection}
          </span>
          {isCapella && (
            <span style={{ fontSize: '10px', padding: '1px 7px', borderRadius: '10px', background: 'rgba(88,166,255,.12)', color: C.blue, border: '1px solid rgba(88,166,255,.25)', fontWeight: 500 }}>
              Capella
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontFamily: mono, fontSize: '12px', color: C.muted }}>
            {total.toLocaleString()} docs
          </span>
          <button
            onClick={onDisconnect}
            style={{ padding: '5px 12px', borderRadius: '6px', border: `1px solid ${C.border}`, background: 'transparent', color: C.muted, fontSize: '12px', cursor: 'pointer' }}
          >
            Disconnect
          </button>
        </div>
      </header>

      {/* Body */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        <Sidebar
          total={total}
          filtered={visibleDocs.length}
          groups={groups}
          themes={themes}
          activeFilter={activeFilter}
          timeRange={timeRange}
          onFilter={handleFilter}
          onSearch={handleSearch}
          onTimeRange={handleTimeRange}
          onAutoCluster={() => setShowCluster(true)}
          clustering={clustering}
        />

        {/* Main content */}
        <main style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
          {noIndex && !loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 20px', textAlign: 'center' }}>
              <div style={{ fontSize: '32px', marginBottom: '12px' }}>🗂</div>
              <div style={{ fontFamily: display, fontSize: '18px', fontWeight: 600, color: C.text, marginBottom: '8px' }}>No index available</div>
              <p style={{ fontSize: '13px', color: C.muted, marginBottom: '24px', maxWidth: '380px', lineHeight: 1.7 }}>
                This collection needs an index before it can be queried. Create secondary indexes on the common filter fields (type, user_id, created_at, block_id) plus a keys-only index on the document ID, so browsing and pagination don't require a primary index.
              </p>
              <button
                onClick={handleCreateIndex}
                disabled={creatingIndex}
                style={{ padding: '10px 24px', borderRadius: '8px', border: 'none', background: C.cbRed, color: '#fff', fontSize: '14px', fontWeight: 600, cursor: creatingIndex ? 'not-allowed' : 'pointer', opacity: creatingIndex ? 0.7 : 1, boxShadow: '0 2px 12px rgba(234,35,40,.4)' }}
              >
                {creatingIndex ? 'Creating indexes…' : 'Create Secondary Indexes'}
              </button>
            </div>
          )}

          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 20px' }}>
              <div style={{ fontFamily: mono, fontSize: '13px', color: C.muted }}>Loading memories…</div>
            </div>
          )}

          {!loading && !noIndex && visibleDocs.length === 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 20px', textAlign: 'center' }}>
              <div style={{ fontSize: '28px', marginBottom: '12px' }}>◉</div>
              <div style={{ fontFamily: display, fontSize: '15px', fontWeight: 600, color: C.text, marginBottom: '8px' }}>No memories match</div>
              {searchVal && (
                <div style={{ fontFamily: mono, fontSize: '11px', color: C.faint, marginTop: '4px' }}>
                  Searched for Block ID or text: <span style={{ color: C.blue }}>{searchVal}</span>
                </div>
              )}
              {timeRange && (
                <div style={{ fontSize: '12px', color: C.faint, marginTop: '8px', maxWidth: '360px', lineHeight: 1.6 }}>
                  Showing last <span style={{ color: C.yellow }}>{timeRange === 'hour' ? '1 hour' : timeRange === 'day' ? '24 hours' : '7 days'}</span>.
                  Filters on <span style={{ fontFamily: mono, color: C.muted }}>created_at</span> — memories without that field are excluded.
                </div>
              )}
            </div>
          )}

          {!loading && !noIndex && visibleDocs.length > 0 && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(310px, 1fr))', gap: '10px' }}>
                {visibleDocs.map(doc => {
                  const themeKey = idToTheme[doc.__cb_key]
                  const themeIdx = themeKey ? Object.keys(themes).indexOf(themeKey) : -1
                  const themeColor = themeIdx >= 0 ? THEME_COLORS[themeIdx % THEME_COLORS.length] : null
                  return (
                    <MemoryCard
                      key={doc.__cb_key}
                      doc={doc}
                      selected={selectedId === doc.__cb_key}
                      theme={themeColor}
                      onSelect={setSelectedId}
                      onDelete={setDeleteId}
                    />
                  )
                })}
              </div>

              {total > LIMIT && (
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '12px', marginTop: '20px', paddingBottom: '8px' }}>
                  <button
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                    style={{ padding: '6px 16px', borderRadius: '6px', border: `1px solid ${C.border}`, background: C.surface, color: offset === 0 ? C.faint : C.text, fontSize: '13px', cursor: offset === 0 ? 'not-allowed' : 'pointer' }}
                  >← Prev</button>
                  <span style={{ fontFamily: mono, fontSize: '12px', color: C.muted }}>
                    {offset + 1}–{Math.min(offset + LIMIT, total)} of {total}
                  </span>
                  <button
                    disabled={offset + LIMIT >= total}
                    onClick={() => setOffset(offset + LIMIT)}
                    style={{ padding: '6px 16px', borderRadius: '6px', border: `1px solid ${C.border}`, background: C.surface, color: offset + LIMIT >= total ? C.faint : C.text, fontSize: '13px', cursor: offset + LIMIT >= total ? 'not-allowed' : 'pointer' }}
                  >Next →</button>
                </div>
              )}
            </>
          )}
        </main>

        {selectedDoc && (
          <DetailPanel
            doc={selectedDoc}
            onClose={() => setSelectedId(null)}
            onDelete={setDeleteId}
          />
        )}
      </div>

      {deleteId && (
        <DeleteConfirm
          docId={deleteId}
          onClose={() => setDeleteId(null)}
          onConfirm={handleDelete}
        />
      )}

      {showCluster && (
        <ClusterModal
          filterParams={clusterParams()}
          onClose={() => setShowCluster(false)}
          onApply={handleApplyThemes}
        />
      )}

      {toast && <Toast msg={toast.msg} type={toast.type} />}
    </div>
  )
}
