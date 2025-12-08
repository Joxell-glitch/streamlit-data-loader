import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

let readDb: Database.Database | null = null;
let writeDb: Database.Database | null = null;

function resolveDatabasePath() {
  if (process.env.DATABASE_PATH) {
    return process.env.DATABASE_PATH;
  }
  return path.resolve(process.cwd(), '..', 'data', 'arb_bot.sqlite');
}

function openDatabase(readonly: boolean) {
  const dbPath = resolveDatabasePath();
  if (!fs.existsSync(dbPath)) {
    throw new Error(`SQLite database not found at ${dbPath}`);
  }
  return new Database(dbPath, { readonly, fileMustExist: true });
}

export function getDb(options: { writable?: boolean } = {}) {
  const writable = options.writable ?? false;
  if (writable) {
    if (!writeDb) {
      writeDb = openDatabase(false);
    }
    return writeDb;
  }

  if (!readDb) {
    readDb = openDatabase(true);
  }
  return readDb;
}
