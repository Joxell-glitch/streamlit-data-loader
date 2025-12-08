import { NextResponse } from 'next/server';
import { getRuns } from '@/lib/data';

export const runtime = 'nodejs';

export async function GET() {
  try {
    const runs = getRuns();
    return NextResponse.json({ runs });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
