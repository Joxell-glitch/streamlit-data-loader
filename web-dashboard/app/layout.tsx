import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Hyperliquid Arb Dashboard',
  description: 'Visualizza le run di paper trading e i trade di arbitraggio triangolare.'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="it">
      <body>
        <main>
          <header>
            <div>
              <h1>Hyperliquid Triangular Arbitrage</h1>
              <p style={{ color: 'var(--muted)', marginTop: 6 }}>
                Dashboard per analizzare le run di paper trading, i trade e i log operativi.
              </p>
            </div>
          </header>
          {children}
        </main>
      </body>
    </html>
  );
}
