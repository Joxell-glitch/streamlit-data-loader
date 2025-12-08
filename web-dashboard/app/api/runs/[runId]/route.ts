import { NextResponse } from 'next/server';
import { getRunDetails } from '@/lib/data';

export const runtime = 'nodejs';

interface Params {
  params: { runId: string };
}

export async function GET(_: Request, { params }: Params) {
  try {
    const details = getRunDetails(params.runId);
    if (!details.metadata) {
      return NextResponse.json({ error: 'Run not found' }, { status: 404 });
    }
    return NextResponse.json(details);
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
