"use client";

import {
  SessionProvider,
  signIn as nextAuthSignIn,
  signOut as nextAuthSignOut,
  useSession,
} from "next-auth/react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

interface AuthResult {
  error?: string;
}

interface FavoritesContextValue {
  favoriteSiteIds: Set<string>;
  toggleFavorite: (siteId: string) => Promise<void>;
}

const FavoritesContext = createContext<FavoritesContextValue>({
  favoriteSiteIds: new Set(),
  toggleFavorite: async () => {},
});

const EMPTY_SET: ReadonlySet<string> = new Set();

function FavoritesProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();
  const userId = session?.user?.id;
  const [fetched, setFetched] = useState<{ userId: string; siteIds: Set<string> } | null>(null);

  useEffect(() => {
    if (!userId) return; // logged-out case is handled by the derived value below, no setState needed
    let cancelled = false;
    (async () => {
      const res = await fetch("/api/favorites");
      if (res.ok && !cancelled) {
        const data = await res.json();
        setFetched({ userId, siteIds: new Set(data.siteIds as string[]) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  // Only trust the fetched set if it belongs to the currently signed-in user
  // -- avoids briefly showing the previous user's favorites after a switch.
  const favoriteSiteIds =
    userId && fetched?.userId === userId ? fetched.siteIds : (EMPTY_SET as Set<string>);

  const toggleFavorite = useCallback(
    async (siteId: string) => {
      if (!userId) return;
      const isFav = favoriteSiteIds.has(siteId);
      const optimistic = new Set(favoriteSiteIds);
      if (isFav) optimistic.delete(siteId);
      else optimistic.add(siteId);
      setFetched({ userId, siteIds: optimistic });

      try {
        if (isFav) {
          await fetch(`/api/favorites/${siteId}`, { method: "DELETE" });
        } else {
          await fetch("/api/favorites", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ siteId }),
          });
        }
      } catch {
        // Revert the optimistic update if the request itself failed (offline, etc).
        const reverted = new Set(favoriteSiteIds);
        setFetched({ userId, siteIds: reverted });
      }
    },
    [userId, favoriteSiteIds]
  );

  return (
    <FavoritesContext.Provider value={{ favoriteSiteIds, toggleFavorite }}>
      {children}
    </FavoritesContext.Provider>
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <FavoritesProvider>{children}</FavoritesProvider>
    </SessionProvider>
  );
}

async function postJson(url: string, body: unknown) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, data };
  } catch {
    return { ok: false, data: { error: "Network error -- check your connection and try again." } };
  }
}

export function useAuth() {
  const { data: session, status } = useSession();
  const { favoriteSiteIds, toggleFavorite } = useContext(FavoritesContext);

  const user: AuthUser | null = session?.user
    ? {
        id: session.user.id,
        email: session.user.email ?? "",
        display_name: session.user.name ?? session.user.email ?? "Account",
      }
    : null;

  const login = useCallback(async (email: string, password: string): Promise<AuthResult> => {
    try {
      const res = await nextAuthSignIn("credentials", { email, password, redirect: false });
      if (res?.error) return { error: "Invalid email or password." };
      return {};
    } catch {
      return { error: "Network error -- check your connection and try again." };
    }
  }, []);

  const signup = useCallback(
    async (email: string, password: string, displayName: string): Promise<AuthResult> => {
      const { ok, data } = await postJson("/api/auth/signup", { email, password, displayName });
      if (!ok) return { error: data.error ?? "Sign up failed." };

      const loginResult = await login(email, password);
      if (loginResult.error) {
        return { error: "Account created -- please sign in." };
      }
      return {};
    },
    [login]
  );

  const logout = useCallback(async () => {
    await nextAuthSignOut({ redirect: false });
  }, []);

  const loginWithGoogle = useCallback(() => {
    void nextAuthSignIn("google", { callbackUrl: "/" });
  }, []);

  return {
    user,
    loading: status === "loading",
    favoriteSiteIds,
    toggleFavorite,
    login,
    signup,
    logout,
    loginWithGoogle,
  };
}
