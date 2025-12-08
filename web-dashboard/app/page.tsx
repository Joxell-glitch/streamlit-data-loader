import Link from 'next/link';
import { getRuns } from '@/lib/data';
import { MetricCard } from './components/MetricCard';

function formatDate(timestamp: number | null) {
  if (!timestamp) return '—';
  return new Date(timestamp * 1000).toLocaleString();
}

function formatDuration(seconds: number | null) {
  if (!seconds) return '—';
  const hours = seconds / 3600;
  return `${hours.toFixed(2)} h`;
}

export default async function HomePage() {
  const runs = getRuns();

  const totals = runs.reduce(
    (acc, run) => {
      acc.trades += run.tradeCount;
      acc.pnl += run.totalPnl;
      return acc;
    },
    { trades: 0, pnl: 0 }
  );

  return (
    <div className="grid" style={{ gridTemplateColumns: '2fr 1fr' }}>
      <div className="panel" style={{ gridColumn: '1 / span 1' }}>
        <h2>Run di paper trading</h2>
        <p className="section-title">Clicca su una run per vedere i dettagli e i trade.</p>
        <div className="table-scroll" style={{ maxHeight: 500 }}>
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Inizio</th>
                <th>Fine</th>
                <th>Trade</th>
                <th>Totale PnL</th>
                <th>Win rate</th>
                <th>Stato</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.runId}>
                  <td>
                    <Link href={`/runs/${run.runId}`} style={{ color: 'var(--accent)' }}>
                      {run.runId}
                    </Link>
                    <div style={{ color: 'var(--muted)', fontSize: 12 }}>{run.notes || '—'}</div>
                  </td>
                  <td>{formatDate(run.startTimestamp)}</td>
                  <td>{formatDate(run.endTimestamp)}</td>
                  <td>{run.tradeCount}</td>
                  <td className={run.totalPnl >= 0 ? 'positive' : 'negative'}>{run.totalPnl.toFixed(5)}</td>
                  <td>{(run.winRate * 100).toFixed(1)}%</td>
                  <td>
                    <span className={`badge ${run.status === 'active' ? 'active' : 'completed'}`}>
                      {run.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: '1fr', gap: 12 }}>
        <MetricCard label="Totale trade" value={totals.trades.toString()} />
        <MetricCard
          label="PnL aggregato"
          value={totals.pnl.toFixed(5)}
          emphasis={totals.pnl >= 0 ? 'positive' : 'negative'}
        />
        <MetricCard label="Run attive" value={runs.filter((r) => r.status === 'active').length.toString()} />
        <MetricCard label="Durata media" value={formatDuration(runs.reduce((acc, r) => acc + (r.durationSeconds || 0), 0) / (runs.length || 1))} />
      </div>
    </div>
  );
}
