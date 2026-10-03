"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";

function GoogleIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className="h-4 w-4">
      <path
        fill="#4285F4"
        d="M23.52 12.27c0-.85-.08-1.67-.22-2.45H12v4.64h6.47c-.28 1.5-1.13 2.77-2.4 3.62v3.01h3.88c2.27-2.09 3.57-5.17 3.57-8.82z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.07 7.95-2.91l-3.88-3.01c-1.08.72-2.45 1.15-4.07 1.15-3.13 0-5.78-2.11-6.73-4.96H1.27v3.11C3.25 21.3 7.31 24 12 24z"
      />
      <path fill="#FBBC05" d="M5.27 14.27a7.2 7.2 0 010-4.54V6.62H1.27a12 12 0 000 10.76l4-3.11z" />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.44-3.44C17.95 1.19 15.24 0 12 0 7.31 0 3.25 2.7 1.27 6.62l4 3.11C6.22 6.86 8.87 4.75 12 4.75z"
      />
    </svg>
  );
}

// Auth.js's own built-in /api/auth/providers endpoint lists exactly which
// providers are actually configured server-side. This renders nothing at all
// (button, card, and the "or" divider) until we know Google is really usable
// -- avoids showing a "Continue with Google" that would just fail before
// GOOGLE_CLIENT_ID/SECRET are set.
export default function GoogleSignInSection() {
  const { loginWithGoogle } = useAuth();
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/providers")
      .then((res) => res.json())
      .then((providers) => {
        if (!cancelled) setAvailable(Boolean(providers?.google));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!available) return null;

  return (
    <>
      <button
        type="button"
        onClick={loginWithGoogle}
        className="flex items-center justify-center gap-2 rounded-xl border border-border-color bg-surface shadow-sm py-2.5 text-sm font-medium text-foreground hover:bg-surface-muted transition-colors w-full"
      >
        <GoogleIcon />
        Continue with Google
      </button>
      <div className="flex items-center gap-3 my-4">
        <div className="h-px flex-1 bg-border-color" />
        <span className="text-xs text-muted-foreground">or</span>
        <div className="h-px flex-1 bg-border-color" />
      </div>
    </>
  );
}
