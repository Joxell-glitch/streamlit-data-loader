'use client';

import { useMemo, useState } from 'react';
import { TradeWithOpportunity } from '@/lib/data';

interface Props {
  trades: TradeWithOpportunity[];
}

function formatPair(opportunity?: TradeWithOpportunity['opportunity']) {
  if (!opportunity) return 'N/D';
  return `${opportunity.asset_a}/${opportunity.asset_b} → ${opportunity.asset_b}/${opportunity.asset_c} → ${opportunity.asset_c}/${opportunity.asset_a}`;
}

export function TradesTable({ trades }: Props) {
  const [assetFilter, setAssetFilter] = useState('');
  const [pnlFilter, setPnlFilter] = useState('all');

  const filtered = useMemo(() => {
    return trades.filter((trade) => {
      const matchesAsset = assetFilter
        ? (trade.opportunity?.asset_a?.toLowerCase().includes(assetFilter.toLowerCase()) ||
            trade.opportunity?.asset_b?.toLowerCase().includes(assetFilter.toLowerCase()) ||
            trade.opportunity?.asset_c?.toLowerCase().includes(assetFilter.toLowerCase()))
        : true;
      const matchesPnl =
        pnlFilter === 'positive'
          ? trade.realized_pnl > 0
          : pnlFilter === 'negative'
          ? trade.realized_pnl < 0
          : true;
      return matchesAsset && matchesPnl;
    });
  }, [assetFilter, pnlFilter, trades]);

  return (
    <div className="panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 className="section-title">Trade dettagliati</h3>
        <div className="controls">
          <input
            placeholder="Filtra per asset"
            value={assetFilter}
            onChange={(e) => setAssetFilter(e.target.value)}
          />
          <select value={pnlFilter} onChange={(e) => setPnlFilter(e.target.value)}>
            <option value="all">Tutti</option>
            <option value="positive">PnL positivo</option>
            <option value="negative">PnL negativo</option>
          </select>
        </div>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Triangolo</th>
              <th>Size</th>
              <th>Edge</th>
              <th>Slippage (1/2/3)</th>
              <th>Fees (1/2/3)</th>
              <th>PnL</th>
              <th>Eseguito</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((trade) => (
              <tr key={trade.id}>
                <td>{new Date(trade.timestamp * 1000).toLocaleString()}</td>
                <td>
                  <div>{formatPair(trade.opportunity)}</div>
                  <div style={{ color: 'var(--muted)', fontSize: 12 }}>
                    Triangle ID: {trade.triangle_id}
                  </div>
                </td>
                <td>{trade.initial_size.toFixed(4)}</td>
                <td>{trade.realized_edge.toFixed(5)}</td>
                <td>
                  {trade.realized_slippage_leg1.toFixed(5)} / {trade.realized_slippage_leg2.toFixed(5)} / {trade.realized_slippage_leg3.toFixed(5)}
                </td>
                <td>
                  {trade.fees_paid_leg1.toFixed(5)} / {trade.fees_paid_leg2.toFixed(5)} / {trade.fees_paid_leg3.toFixed(5)}
                </td>
                <td className={trade.realized_pnl >= 0 ? 'positive' : 'negative'}>
                  {trade.realized_pnl.toFixed(5)}
                </td>
                <td>{trade.was_executed ? 'Sì' : 'No'}</td>
                <td style={{ maxWidth: 160 }}>{trade.reason_if_not_executed || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
