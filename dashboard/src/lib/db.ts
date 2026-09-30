// Real, self-contained storage -- a local SQLite file (not a mock).
// Lives outside src/ under .data/ (gitignored: it holds real password hashes
// and user content, never fixture data). Server-only: this file is only
// ever imported from Route Handlers and src/auth.ts, never from a Client
// Component.

import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import path from "node:path";

const DATA_DIR = path.join(process.cwd(), ".data");
mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(path.join(DATA_DIR, "app.db"));
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,               -- NULL for Google-only accounts
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'credentials', -- 'credentials' | 'google'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );

  -- No sessions table: Auth.js (src/auth.ts) owns session state itself via
  -- its own signed JWT cookie, for both the Google and Credentials providers.

  CREATE TABLE IF NOT EXISTS favorite_sites (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, site_id)
  );

  CREATE TABLE IF NOT EXISTS site_notes (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site_id TEXT NOT NULL,
    note TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, site_id)
  );

  -- UI + storage only for now: nothing currently sends a real notification.
  -- Stages 5-9 (model/detectors/API) don't exist yet to trigger one from.
  CREATE TABLE IF NOT EXISTS alert_preferences (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site_id TEXT NOT NULL,
    notify_on_elevated_risk INTEGER NOT NULL DEFAULT 0,
    notify_on_any_change INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, site_id)
  );
`);

export default db;
