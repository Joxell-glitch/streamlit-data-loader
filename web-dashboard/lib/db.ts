import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

let db: Database.Database | null = null;

function resolveDatabasePath() {
  if (process.env.DATABASE_PATH) {
    return process.env.DATABASE_PATH;
  }
  return path.resolve(process.cwd(), '..', 'data', 'arb_bot.sqlite');
}

export function getDb() {
  if (!db) {
    const dbPath = resolveDatabasePath();
    if (!fs.existsSync(dbPath)) {
      throw new Error(`SQLite database not found at ${dbPath}`);
    }
    db = new Database(dbPath, { readonly: true });
  }
  return db;
}
