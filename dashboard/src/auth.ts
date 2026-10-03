// Auth.js (NextAuth v5) config -- proper OAuth (Google) plus a Credentials
// provider that reuses the existing SQLite `users` table, so favorites/notes/
// alert-preferences all key off the same stable internal user id regardless
// of how someone signed in.
//
// Google requires real credentials from Google Cloud Console
// (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env.local) -- see
// dashboard/README-auth.md for the exact setup steps. Without them, the
// Google provider is simply omitted and email/password still works fully.

import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import { createUser, findUserByEmail, verifyPassword } from "@/lib/auth";

const googleConfigured = Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    ...(googleConfigured
      ? [
          Google({
            clientId: process.env.GOOGLE_CLIENT_ID,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET,
          }),
        ]
      : []),
    Credentials({
      credentials: { email: {}, password: {} },
      authorize: async (credentials) => {
        const email = String(credentials?.email ?? "")
          .trim()
          .toLowerCase();
        const password = String(credentials?.password ?? "");
        const row = findUserByEmail(email);
        if (!row || !row.password_hash) return null;
        if (!(await verifyPassword(password, row.password_hash))) return null;
        return { id: row.id, email: row.email, name: row.display_name };
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  callbacks: {
    // First-time Google sign-in: create a matching row in our own `users`
    // table (password_hash = null) so every feature can key off one user id.
    async signIn({ user, account }) {
      if (account?.provider === "google" && user.email) {
        const email = user.email.toLowerCase();
        if (!findUserByEmail(email)) {
          createUser(email, null, user.name ?? email, "google");
        }
      }
      return true;
    },
    async jwt({ token, user }) {
      const email = user?.email ?? token.email;
      if (email) {
        const row = findUserByEmail(String(email).toLowerCase());
        if (row) token.uid = row.id;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.uid) {
        session.user.id = token.uid as string;
      }
      return session;
    },
  },
});

export const isGoogleConfigured = googleConfigured;
