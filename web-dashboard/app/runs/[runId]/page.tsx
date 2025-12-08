import Link from 'next/link';
import { getRunDetails } from '@/lib/data';
import { MetricCard } from '../../components/MetricCard';
import { EquityChart } from '../../components/EquityChart';
import { PnlBarChart } from '../../components/PnlBarChart';
import { TradesTable } from '../../components/TradesTable';
import { LogsViewer } from '../../components/LogsViewer';

interface Params {
  params: { runId: string };
}

function formatDate(timestamp: number | null | undefined) {
  if (!timestamp) return '—';
  return new Date(timestamp * 1000).toLocaleString();
}

function formatSeconds(seconds: number | null | undefined) {
  if (!seconds) return '—';
  const hours = seconds / 3600;
  return `${hours.toFixed(2)} h`;
}

export default function RunPage({ params }: Params) {
  const details = getRunDetails(params.runId);

  if (!details.metadata) {
    return (
      <div className="panel">
        <p>Run non trovata.</p>
        <Link href="/">Torna alla lista</Link>
      </div>
    );
  }

  const { metadata, trades, equityCurve, maxDrawdown } = details;
  const pnlSeries = trades.map((t) => ({ timestamp: t.timestamp, pnl: t.realized_pnl }));

  return (
    <div className="grid" style={{ gridTemplateColumns: '2fr 1fr', gap: 12 }}>
      <div style={{ gridColumn: '1 / span 2' }} className="panel">
        <Link href="/" style={{ color: 'var(--accent)' }}>
          ← Torna alle run
        </Link>
        <h2 style={{ marginTop: 12 }}>{metadata.runId}</h2>
        <p className="section-title">{metadata.notes || 'Nessuna nota per questa run.'}</p>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <span className={`badge ${metadata.status === 'active' ? 'active' : 'completed'}`}>{metadata.status}</span>
          <span className="badge">{trades.length} trade</span>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gridColumn: '1 / span 2' }}>
        <MetricCard label="Inizio" value={formatDate(metadata.startTimestamp)} />
        <MetricCard label="Fine" value={formatDate(metadata.endTimestamp)} />
        <MetricCard label="Durata" value={formatSeconds(metadata.durationSeconds)} />
        <MetricCard label="Totale PnL" value={metadata.totalPnl.toFixed(5)} emphasis={metadata.totalPnl >= 0 ? 'positive' : 'negative'} />
        <MetricCard label="PnL medio" value={metadata.averagePnl.toFixed(5)} />
        <MetricCard label="Win rate" value={`${(metadata.winRate * 100).toFixed(1)}%`} />
        <MetricCard label="Max drawdown" value={maxDrawdown.toFixed(5)} emphasis={maxDrawdown > 0 ? 'negative' : 'neutral'} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gridColumn: '1 / span 2', gap: 12 }}>
        <EquityChart data={equityCurve} />
        <PnlBarChart data={pnlSeries} />
      </div>

      <div style={{ gridColumn: '1 / span 2' }}>
        <TradesTable trades={trades} />
      </div>

      <div style={{ gridColumn: '1 / span 2' }}>
        <LogsViewer />
      </div>
    </div>
  );
}
