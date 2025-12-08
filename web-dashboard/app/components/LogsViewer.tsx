'use client';

import { useEffect, useState } from 'react';

export function LogsViewer() {
  const [lines, setLines] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const res = await fetch('/api/logs');
      const json = await res.json();
      setLines(json.lines ?? []);
      setMessage(json.message ?? null);
    } catch (err: any) {
      setMessage(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 className="section-title">Log recenti</h3>
        <button
          onClick={load}
          style={{
            background: 'var(--accent)',
            border: 'none',
            color: '#0a0f1f',
            borderRadius: 8,
            padding: '8px 12px',
            cursor: 'pointer',
            fontWeight: 600
          }}
        >
          {loading ? 'Aggiorno…' : 'Aggiorna'}
        </button>
      </div>
      {message && <div style={{ color: 'var(--negative)', marginBottom: 8 }}>{message}</div>}
      <div className="log-viewer">
        {lines.map((line, idx) => (
          <div key={idx}>{line}</div>
        ))}
        {(!lines || lines.length === 0) && <div>Nessuna riga di log disponibile.</div>}
      </div>
    </div>
  );
}
