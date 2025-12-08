import { NextResponse } from 'next/server';

import { setBotEnabled } from '@/lib/data';

export const runtime = 'nodejs';

export async function POST(request: Request) {
  try {
    const body = await request.json();
    if (typeof body?.enabled !== 'boolean') {
      return NextResponse.json({ ok: false, message: 'Invalid payload' }, { status: 400 });
    }

    const status = setBotEnabled(body.enabled);
    return NextResponse.json({
      ok: true,
      botEnabled: status.botEnabled,
      botRunning: status.botRunning,
      wsConnected: status.wsConnected,
      dbConnected: status.dbConnected,
      lastHeartbeat: status.lastHeartbeat
    });
  } catch (error: any) {
    return NextResponse.json(
      { ok: false, dbConnected: false, error: error.message },
      { status: 500 }
    );
  }
}
