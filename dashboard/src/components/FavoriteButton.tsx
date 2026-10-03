"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.75}
      className="h-4 w-4"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z"
      />
    </svg>
  );
}

export default function FavoriteButton({ siteId }: { siteId: string }) {
  const { user, favoriteSiteIds, toggleFavorite } = useAuth();
  const isFavorite = favoriteSiteIds.has(siteId);

  if (!user) {
    return (
      <Link
        href="/login"
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-accent transition-colors"
        title="Sign in to save favorite sites"
      >
        <HeartIcon filled={false} />
        Save
      </Link>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void toggleFavorite(siteId)}
      className={`flex items-center gap-1.5 text-sm transition-colors ${
        isFavorite ? "text-rose-600 dark:text-rose-400" : "text-muted-foreground hover:text-accent"
      }`}
    >
      <HeartIcon filled={isFavorite} />
      {isFavorite ? "Saved" : "Save"}
    </button>
  );
}
