'use client';

import { Line, LineChart, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface Props {
  data: { timestamp: number; equity: number }[];
}

export function EquityChart({ data }: Props) {
  const formatted = data.map((d) => ({
    time: new Date(d.timestamp * 1000).toLocaleString(),
    equity: Number(d.equity.toFixed(4))
  }));

  return (
    <div className="panel" style={{ height: 340 }}>
      <h3 className="section-title">Equity curve</h3>
      <ResponsiveContainer width="100%" height="90%">
        <LineChart data={formatted}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2942" />
          <XAxis dataKey="time" tick={{ fill: 'var(--muted)', fontSize: 12 }} hide={formatted.length > 30} />
          <YAxis tick={{ fill: 'var(--muted)', fontSize: 12 }} domain={['dataMin', 'dataMax']} />
          <Tooltip contentStyle={{ background: '#0a0f1f', border: '1px solid var(--border)' }} />
          <Line type="monotone" dataKey="equity" stroke="var(--accent)" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
