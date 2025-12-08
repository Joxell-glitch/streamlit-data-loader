import { getDb } from './db';

export type RunSummary = {
  runId: string;
  startTimestamp: number;
  endTimestamp: number | null;
  notes: string | null;
  tradeCount: number;
  totalPnl: number;
  averagePnl: number;
  winRate: number;
  durationSeconds: number | null;
  status: 'active' | 'completed';
};

export type Opportunity = {
  id: number;
  run_id: string;
  timestamp: number;
  triangle_id: number;
  asset_a: string;
  asset_b: string;
  asset_c: string;
  initial_size: number;
  theoretical_final_amount: number;
  theoretical_edge: number;
  estimated_slippage_leg1: number;
  estimated_slippage_leg2: number;
  estimated_slippage_leg3: number;
  parameters_snapshot: unknown;
};

export type PaperTrade = {
  id: number;
  run_id: string;
  timestamp: number;
  triangle_id: number;
  initial_size: number;
  realized_final_amount: number;
  realized_pnl: number;
  realized_edge: number;
  realized_slippage_leg1: number;
  realized_slippage_leg2: number;
  realized_slippage_leg3: number;
  fees_paid_leg1: number;
  fees_paid_leg2: number;
  fees_paid_leg3: number;
  was_executed: boolean;
  reason_if_not_executed: string | null;
};

export type PortfolioSnapshot = {
  id: number;
  run_id: string;
  timestamp: number;
  balances: unknown;
  total_value_in_quote: number;
};

export type TradeWithOpportunity = PaperTrade & {
  opportunity?: Opportunity | null;
};

export type RunDetails = {
  metadata: RunSummary | null;
  trades: TradeWithOpportunity[];
  opportunities: Opportunity[];
  snapshots: PortfolioSnapshot[];
  equityCurve: { timestamp: number; equity: number }[];
  maxDrawdown: number;
};

export type RuntimeStatus = {
  botEnabled: boolean;
  botRunning: boolean;
  wsConnected: boolean;
  dbConnected: boolean;
  lastHeartbeat: string | null;
};

function computeMaxDrawdown(equityCurve: { equity: number }[]) {
  let peak = 0;
  let maxDrawdown = 0;
  for (const point of equityCurve) {
    peak = Math.max(peak, point.equity);
    const drawdown = peak - point.equity;
    maxDrawdown = Math.max(maxDrawdown, drawdown);
  }
  return maxDrawdown;
}

export function getRuns(): RunSummary[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT rm.run_id, rm.start_timestamp, rm.end_timestamp, rm.notes,
              COUNT(pt.id) as trade_count,
              COALESCE(SUM(pt.realized_pnl), 0) as total_pnl,
              CASE WHEN COUNT(pt.id) > 0 THEN AVG(pt.realized_pnl) ELSE 0 END as avg_pnl,
              SUM(CASE WHEN pt.realized_pnl > 0 THEN 1 ELSE 0 END) as win_count
       FROM run_metadata rm
       LEFT JOIN paper_trades pt ON rm.run_id = pt.run_id
       GROUP BY rm.run_id
       ORDER BY rm.start_timestamp DESC`
    )
    .all();

  return rows.map((row: any) => {
    const durationSeconds = row.end_timestamp ? row.end_timestamp - row.start_timestamp : null;
    const status: 'active' | 'completed' = row.end_timestamp ? 'completed' : 'active';
    const winRate = row.trade_count > 0 ? row.win_count / row.trade_count : 0;

    return {
      runId: row.run_id,
      startTimestamp: row.start_timestamp,
      endTimestamp: row.end_timestamp ?? null,
      notes: row.notes ?? null,
      tradeCount: row.trade_count,
      totalPnl: row.total_pnl,
      averagePnl: row.avg_pnl,
      winRate,
      durationSeconds,
      status
    } as RunSummary;
  });
}

function getRunMetadata(runId: string): RunSummary | null {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT rm.run_id, rm.start_timestamp, rm.end_timestamp, rm.notes,
              COUNT(pt.id) as trade_count,
              COALESCE(SUM(pt.realized_pnl), 0) as total_pnl,
              CASE WHEN COUNT(pt.id) > 0 THEN AVG(pt.realized_pnl) ELSE 0 END as avg_pnl,
              SUM(CASE WHEN pt.realized_pnl > 0 THEN 1 ELSE 0 END) as win_count
       FROM run_metadata rm
       LEFT JOIN paper_trades pt ON rm.run_id = pt.run_id
       WHERE rm.run_id = ?
       GROUP BY rm.run_id`
    )
    .get(runId);
  if (!row) return null;
  const durationSeconds = row.end_timestamp ? row.end_timestamp - row.start_timestamp : null;
  const status: 'active' | 'completed' = row.end_timestamp ? 'completed' : 'active';
  const winRate = row.trade_count > 0 ? row.win_count / row.trade_count : 0;

  return {
    runId: row.run_id,
    startTimestamp: row.start_timestamp,
    endTimestamp: row.end_timestamp ?? null,
    notes: row.notes ?? null,
    tradeCount: row.trade_count,
    totalPnl: row.total_pnl,
    averagePnl: row.avg_pnl,
    winRate,
    durationSeconds,
    status
  };
}

function getOpportunities(runId: string): Opportunity[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT * FROM opportunities WHERE run_id = ? ORDER BY timestamp ASC`
    )
    .all(runId);
  return rows as Opportunity[];
}

function getPortfolioSnapshots(runId: string): PortfolioSnapshot[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT * FROM portfolio_snapshots WHERE run_id = ? ORDER BY timestamp ASC`
    )
    .all(runId);
  return rows as PortfolioSnapshot[];
}

function getTrades(runId: string): PaperTrade[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT * FROM paper_trades WHERE run_id = ? ORDER BY timestamp ASC`
    )
    .all(runId);
  return rows as PaperTrade[];
}

function attachOpportunitiesToTrades(trades: PaperTrade[], opportunities: Opportunity[]): TradeWithOpportunity[] {
  if (!opportunities.length) return trades;
  return trades.map((trade) => {
    const related = opportunities
      .filter((opp) => opp.triangle_id === trade.triangle_id && opp.timestamp <= trade.timestamp)
      .sort((a, b) => b.timestamp - a.timestamp)[0];
    return { ...trade, opportunity: related ?? null };
  });
}

export function getRunDetails(runId: string): RunDetails {
  const metadata = getRunMetadata(runId);
  const opportunities = getOpportunities(runId);
  const snapshots = getPortfolioSnapshots(runId);
  const trades = getTrades(runId);
  const tradesWithOpp = attachOpportunitiesToTrades(trades, opportunities);

  let cumulative = 0;
  const equityCurve = tradesWithOpp.map((trade) => {
    cumulative += trade.realized_pnl ?? 0;
    return { timestamp: trade.timestamp, equity: cumulative };
  });

  const maxDrawdown = computeMaxDrawdown(equityCurve);

  return {
    metadata,
    trades: tradesWithOpp,
    opportunities,
    snapshots,
    equityCurve,
    maxDrawdown
  };
}

export function getRuntimeStatus(): RuntimeStatus {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT bot_enabled, bot_running, ws_connected, last_heartbeat
       FROM runtime_status WHERE id = 1`
    )
    .get();

  if (!row) {
    throw new Error('runtime_status row not found');
  }

  return {
    botEnabled: Boolean(row.bot_enabled),
    botRunning: Boolean(row.bot_running),
    wsConnected: Boolean(row.ws_connected),
    dbConnected: true,
    lastHeartbeat: row.last_heartbeat ? new Date(row.last_heartbeat * 1000).toISOString() : null
  };
}

export function setBotEnabled(enabled: boolean): RuntimeStatus {
  const db = getDb({ writable: true });
  db.prepare(
    `INSERT OR IGNORE INTO runtime_status (id, bot_enabled, bot_running, ws_connected, last_heartbeat)
     VALUES (1, 1, 0, 0, NULL)`
  ).run();
  db.prepare(`UPDATE runtime_status SET bot_enabled = @enabled WHERE id = 1`).run({ enabled: enabled ? 1 : 0 });
  return getRuntimeStatus();
}
