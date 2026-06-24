import { useState } from 'react'
import ConnectionScreen from './components/ConnectionScreen'
import MemoryDashboard from './components/MemoryDashboard'

export default function App() {
  const [connection, setConnection] = useState(null)

  const handleConnect = (info) => setConnection(info)

  const handleDisconnect = async () => {
    try { await fetch('/api/connect', { method: 'DELETE' }) } catch (_) {}
    setConnection(null)
  }

  if (!connection) return <ConnectionScreen onConnect={handleConnect} />
  return <MemoryDashboard connection={connection} onDisconnect={handleDisconnect} />
}
