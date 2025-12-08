'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { IndicatorStatus, StatusIndicator } from './StatusIndicator';

type StatusResponse = {
  ok: boolean;
  botEnabled?: boolean;
  botRunning?: boolean;
  wsConnected?: boolean;
  dbConnected?: boolean;
  lastHeartbeat?: string | null;
  error?: string;
};

export function SystemStatus() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [togglePending, setTogglePending] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status');
      const data: StatusResponse = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Impossibile leggere lo stato');
      }
      setStatus(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Errore di connessione');
      setStatus((prev) => (prev ? { ...prev, ok: false, dbConnected: false } : { ok: false, dbConnected: false }));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const statusIndicators = useMemo(() => {
    const botRunningStatus: IndicatorStatus = loading
      ? 'unknown'
      : status?.botRunning
      ? 'ok'
      : 'error';
    const wsStatus: IndicatorStatus = loading
      ? 'unknown'
      : status?.wsConnected
      ? 'ok'
      : 'error';
    const dbStatus: IndicatorStatus = loading
      ? 'unknown'
      : status?.dbConnected && status?.ok
      ? 'ok'
      : 'error';

    return { botRunningStatus, wsStatus, dbStatus };
  }, [loading, status]);

  const handleToggle = async (enabled: boolean) => {
    if (!status) return;
    const previousEnabled = status.botEnabled ?? false;
    setTogglePending(true);
    setStatus({ ...status, botEnabled: enabled });
    try {
      const res = await fetch('/api/status/bot-enabled', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
      });
      const data: StatusResponse = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Aggiornamento stato bot fallito');
      }
      setStatus(data);
      setError(null);
    } catch (err: any) {
      setStatus((prev) => (prev ? { ...prev, botEnabled: previousEnabled } : prev));
      setError(err.message || 'Errore di connessione');
    } finally {
      setTogglePending(false);
    }
  };

  return (
    <div className="panel" style={{ gridColumn: '1 / span 2' }}>
      <h2>Stato sistema</h2>
      <div className="status-section">
        <StatusIndicator
          label="Bot paper trading"
          status={statusIndicators.botRunningStatus}
          description={loading ? 'Caricamento...' : status?.botRunning ? 'Running' : 'Fermo'}
        />
        <StatusIndicator
          label="WebSocket Hyperliquid"
          status={statusIndicators.wsStatus}
          description={loading ? 'Caricamento...' : status?.wsConnected ? 'Connesso' : 'Disconnesso'}
        />
        <StatusIndicator
          label="Dashboard ↔ DB"
          status={statusIndicators.dbStatus}
          description={loading ? 'Caricamento...' : status?.dbConnected ? 'Online' : 'Errore connessione'}
        />
      </div>
      <div className="status-actions">
        <label className="toggle-label">
          <input
            type="checkbox"
            checked={Boolean(status?.botEnabled)}
            onChange={(e) => handleToggle(e.target.checked)}
            disabled={togglePending || loading}
          />
          Bot abilitato
        </label>
        {status?.lastHeartbeat && (
          <span style={{ color: 'var(--muted)', fontSize: 13 }}>
            Ultimo heartbeat: {new Date(status.lastHeartbeat).toLocaleString()}
          </span>
        )}
      </div>
      {error && <div className="error-text">{error}</div>}
    </div>
  );
}
