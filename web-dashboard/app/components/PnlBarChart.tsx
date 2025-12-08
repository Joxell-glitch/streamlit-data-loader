'use client';

import { BarChart, Bar, CartesianGrid, Tooltip, XAxis, YAxis, ResponsiveContainer } from 'recharts';

interface Props {
  data: { timestamp: number; pnl: number }[];
}

export function PnlBarChart({ data }: Props) {
  const formatted = data.map((d, idx) => ({
    label: `${idx + 1}`,
    pnl: Number(d.pnl.toFixed(4)),
    time: new Date(d.timestamp * 1000).toLocaleString()
  }));
  return (
    <div className="panel" style={{ height: 340 }}>
      <h3 className="section-title">PnL per trade</h3>
      <ResponsiveContainer width="100%" height="90%">
        <BarChart data={formatted}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2942" />
          <XAxis dataKey="label" tick={{ fill: 'var(--muted)', fontSize: 12 }} />
          <YAxis tick={{ fill: 'var(--muted)', fontSize: 12 }} />
          <Tooltip contentStyle={{ background: '#0a0f1f', border: '1px solid var(--border)' }} />
          <Bar dataKey="pnl" fill="var(--accent)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
