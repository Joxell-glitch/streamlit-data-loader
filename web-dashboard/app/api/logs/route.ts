import fs from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

const DEFAULT_LOG_PATH = path.resolve(process.cwd(), '..', 'data', 'bot.log');

function readLogLines(limit: number) {
  const logPath = process.env.LOG_FILE_PATH || DEFAULT_LOG_PATH;
  if (!fs.existsSync(logPath)) {
    return { lines: [], message: `Log file not found at ${logPath}` };
  }
  const content = fs.readFileSync(logPath, 'utf-8');
  const lines = content.trim().split(/\r?\n/);
  const start = Math.max(0, lines.length - limit);
  return { lines: lines.slice(start), message: null };
}

export async function GET() {
  try {
    const { lines, message } = readLogLines(200);
    return NextResponse.json({ lines, message });
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
