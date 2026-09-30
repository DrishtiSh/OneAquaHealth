// Server-only user-table helpers. Session/cookie handling itself now lives
// in src/auth.ts (Auth.js) -- this file only ever touches the `users` table.
// Never import this from a Client Component.

import { randomUUID } from "node:crypto";
import bcrypt from "bcryptjs";
import db from "@/lib/db";

const BCRYPT_COST = 12;

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export function isValidEmail(email: string): boolean {
  // Deliberately simple -- good enough to catch typos, not a full RFC 5322 validator.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

export function isValidPassword(password: string): boolean {
  return password.length >= 8;
}

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, BCRYPT_COST);
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

export interface UserRow {
  id: string;
  email: string;
  password_hash: string | null;
  display_name: string;
  provider: "credentials" | "google";
}

export function findUserByEmail(email: string): UserRow | undefined {
  return db.prepare("SELECT * FROM users WHERE email = ?").get(email) as UserRow | undefined;
}

export function createUser(
  email: string,
  passwordHash: string | null,
  displayName: string,
  provider: "credentials" | "google" = "credentials"
): AuthUser {
  const id = randomUUID();
  db.prepare(
    "INSERT INTO users (id, email, password_hash, display_name, provider) VALUES (?, ?, ?, ?, ?)"
  ).run(id, email, passwordHash, displayName, provider);
  return { id, email, display_name: displayName };
}
