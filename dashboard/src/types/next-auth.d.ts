import type { DefaultSession } from "next-auth";

// Augments Auth.js's default types with our own internal user id, set in
// src/auth.ts's jwt/session callbacks.
declare module "next-auth" {
  interface Session {
    user: {
      id: string;
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    uid?: string;
  }
}
