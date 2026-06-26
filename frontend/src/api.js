async function req(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(data.detail || 'Request failed'), { status: res.status, detail: data.detail })
  return data
}

export const api = {
  connect: (payload) => req('POST', '/connect', payload),
  disconnect: () => req('DELETE', '/connect'),
  listScopes: (bucket) => req('GET', `/buckets/${encodeURIComponent(bucket)}/scopes`),
  listCollections: (bucket, scope) =>
    req('GET', `/buckets/${encodeURIComponent(bucket)}/scopes/${encodeURIComponent(scope)}/collections`),
  selectCollection: (bucket, scope, collection) =>
    req('POST', '/collection', { bucket, scope, collection }),
  createIndex: () => req('POST', '/index'),

  listMemories: ({ search, type, user_id, time_range, limit = 50, offset = 0 } = {}) => {
    const qs = new URLSearchParams()
    if (search) qs.set('search', search)
    if (type) qs.set('type', type)
    if (user_id) qs.set('user_id', user_id)
    if (time_range) qs.set('time_range', time_range)
    qs.set('limit', limit)
    qs.set('offset', offset)
    return req('GET', `/memories?${qs}`)
  },
  getGroups: () => req('GET', '/memories/groups'),
  updateMemory: (docId, data) => req('PUT', `/memories/${encodeURIComponent(docId)}`, { data }),
  deleteMemory: (docId) => req('DELETE', `/memories/${encodeURIComponent(docId)}`),
}
