"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

export default function UserMenu() {
  const { user, loading, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  if (loading) {
    return <span className="h-8 w-16 shrink-0 rounded-lg bg-surface animate-pulse" />;
  }

  if (!user) {
    return (
      <div className="flex items-center gap-2">
        <Link
          href="/login"
          className="text-sm font-medium text-muted-foreground hover:text-foreground px-2 py-1.5 transition-colors"
        >
          Sign in
        </Link>
        <Link
          href="/signup"
          className="text-sm font-medium bg-accent text-accent-foreground rounded-lg px-3 py-1.5 hover:opacity-90 transition-opacity"
        >
          Sign up
        </Link>
      </div>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-border-color bg-surface px-2 py-1.5 hover:bg-surface-muted transition-colors"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-accent-foreground text-xs font-bold">
          {user.display_name.charAt(0).toUpperCase()}
        </span>
        <span className="text-sm font-medium text-foreground hidden sm:inline">
          {user.display_name}
        </span>
      </button>

      {menuOpen && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setMenuOpen(false)} />
          <div className="absolute right-0 top-full mt-2 z-40 w-48 rounded-lg border border-border-color bg-surface shadow-lg py-1">
            <div className="px-3 py-2 border-b border-border-color">
              <p className="text-sm font-medium text-foreground truncate">{user.display_name}</p>
              <p className="text-xs text-muted-foreground truncate">{user.email}</p>
            </div>
            <Link
              href="/settings/alerts"
              onClick={() => setMenuOpen(false)}
              className="block w-full text-left px-3 py-2 text-sm text-foreground hover:bg-surface-muted transition-colors"
            >
              Alert preferences
            </Link>
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                void logout();
              }}
              className="w-full text-left px-3 py-2 text-sm text-foreground hover:bg-surface-muted transition-colors border-t border-border-color"
            >
              Log out
            </button>
          </div>
        </>
      )}
    </div>
  );
}
