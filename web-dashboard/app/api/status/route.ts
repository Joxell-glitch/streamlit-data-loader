import { NextResponse } from 'next/server';

import { getRuntimeStatus } from '@/lib/data';

export const runtime = 'nodejs';

export async function GET() {
  try {
    const status = getRuntimeStatus();
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
