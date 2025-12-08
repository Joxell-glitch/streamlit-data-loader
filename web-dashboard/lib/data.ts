export type RunSummary = {
  id: number;
  runId: string;
  startTimestamp: number | null;
  endTimestamp: number | null;
  totalTrades: number;
  totalPnl: number;
  winRate: number;
  status: 'running' | 'completed';
};

export type Trade = {
  id: number;
  runId: string;
  pairPath: string | null;
  entryPrice: number | null;
  exitPrice: number | null;
  size: number | null;
  pnl: number | null;
  timestamp: number | null;
};

export type StatusSummary = {
  botRunning: boolean;
  websocketConnected: boolean;
  dashboardConnected: boolean;
  lastHeartbeat: number | null;
  botEnabled: boolean;
};

import { API_BASE_URL, getApiBaseUrl } from './api';

async function fetchFromApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}${path}`, {
    cache: 'no-store',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {})
    }
  });

  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || `Request failed for ${path}`);
  }

  return res.json() as Promise<T>;
}

export async function fetchRuns(): Promise<RunSummary[]> {
  type RunApiResponse = {
    id: number;
    run_id: string;
    start_timestamp: number | null;
    end_timestamp: number | null;
    total_trades: number;
    total_pnl: number;
    win_rate: number;
    status: string;
  };

  const runs = await fetchFromApi<RunApiResponse[]>(`/api/runs`);
  return runs.map((run) => ({
    id: run.id,
    runId: run.run_id,
    startTimestamp: run.start_timestamp,
    endTimestamp: run.end_timestamp,
    totalTrades: run.total_trades,
    totalPnl: run.total_pnl,
    winRate: run.win_rate,
    status: run.status === 'completed' ? 'completed' : 'running'
  }));
}

export async function fetchTrades(runId?: string): Promise<Trade[]> {
  type TradeApiResponse = {
    id: number;
    run_id: string;
    pair_path: string | null;
    entry_price: number | null;
    exit_price: number | null;
    size: number | null;
    pnl: number | null;
    timestamp: number | null;
  };

  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
  const trades = await fetchFromApi<TradeApiResponse[]>(`/api/trades${query}`);
  return trades.map((trade) => ({
    id: trade.id,
    runId: trade.run_id,
    pairPath: trade.pair_path,
    entryPrice: trade.entry_price,
    exitPrice: trade.exit_price,
    size: trade.size,
    pnl: trade.pnl,
    timestamp: trade.timestamp
  }));
}

export async function fetchStatus(): Promise<StatusSummary> {
  type StatusApiResponse = {
    bot_running: boolean;
    websocket_connected: boolean;
    dashboard_connected: boolean;
    last_heartbeat: number | null;
    bot_enabled: boolean;
  };

  const data = await fetchFromApi<StatusApiResponse>(`/api/status`);
  return {
    botRunning: Boolean(data.bot_running),
    websocketConnected: Boolean(data.websocket_connected),
    dashboardConnected: Boolean(data.dashboard_connected),
    lastHeartbeat: data.last_heartbeat,
    botEnabled: Boolean(data.bot_enabled)
  };
}

export async function startBot(): Promise<StatusSummary> {
  const data = await fetchFromApi(`/api/start`, { method: 'POST' });
  return {
    botRunning: Boolean((data as any).bot_running),
    websocketConnected: Boolean((data as any).websocket_connected),
    dashboardConnected: Boolean((data as any).dashboard_connected),
    lastHeartbeat: (data as any).last_heartbeat ?? null,
    botEnabled: Boolean((data as any).bot_enabled)
  };
}

export async function stopBot(): Promise<StatusSummary> {
  const data = await fetchFromApi(`/api/stop`, { method: 'POST' });
  return {
    botRunning: Boolean((data as any).bot_running),
    websocketConnected: Boolean((data as any).websocket_connected),
    dashboardConnected: Boolean((data as any).dashboard_connected),
    lastHeartbeat: (data as any).last_heartbeat ?? null,
    botEnabled: Boolean((data as any).bot_enabled)
  };
}

export async function fetchLogs(): Promise<string[]> {
  const data = await fetchFromApi<{ lines: string[] }>(`/api/logs`);
  return data.lines || [];
}

export { getApiBaseUrl };
