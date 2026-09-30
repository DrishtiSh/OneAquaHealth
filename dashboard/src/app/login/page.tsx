"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import Logo from "@/components/Logo";
import GoogleSignInButton from "@/components/GoogleSignInButton";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const result = await login(email, password);
    setSubmitting(false);
    if (result.error) setError(result.error);
    else router.push("/");
  }

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-2 mb-6 text-center">
          <Logo size={40} />
          <h1 className="text-xl font-semibold text-foreground">Welcome back</h1>
          <p className="text-sm text-muted-foreground">
            Sign in for favorites, notes, and alert preferences. Browsing stream data never
            requires an account.
          </p>
        </div>

        <GoogleSignInButton />

        <form
          onSubmit={handleSubmit}
          className="flex flex-col gap-4 rounded-xl border border-border-color bg-surface shadow-sm p-6"
        >
          {error && (
            <p className="text-sm text-rose-700 dark:text-rose-300 bg-rose-100 dark:bg-rose-500/10 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-foreground font-medium">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-lg border border-border-color bg-surface-muted px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="you@example.com"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-foreground font-medium">Password</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-lg border border-border-color bg-surface-muted px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;"
            />
          </label>
          <button
            type="submit"
            disabled={submitting}
            className="mt-2 rounded-lg bg-accent text-accent-foreground font-medium py-2 text-sm hover:opacity-90 transition-opacity disabled:opacity-60"
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="text-center text-sm text-muted-foreground mt-4">
          Don&apos;t have an account?{" "}
          <Link href="/signup" className="text-accent font-medium hover:underline">
            Sign up
          </Link>
        </p>
      </div>
    </main>
  );
}
