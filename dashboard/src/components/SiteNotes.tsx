"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";

const MAX_LENGTH = 1000;

export default function SiteNotes({ siteId }: { siteId: string }) {
  const { user, loading: authLoading } = useAuth();
  const [note, setNote] = useState("");
  const [savedNote, setSavedNote] = useState("");
  const [fetchedFor, setFetchedFor] = useState<string | null>(null); // `${userId}:${siteId}` once loaded
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return; // logged-out case is handled by the derived check below, no setState needed
    let cancelled = false;
    (async () => {
      const res = await fetch(`/api/notes/${siteId}`);
      if (res.ok && !cancelled) {
        const data = await res.json();
        setNote(data.note);
        setSavedNote(data.note);
        setFetchedFor(`${user.id}:${siteId}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [siteId, user]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    const res = await fetch(`/api/notes/${siteId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    if (res.ok) {
      const data = await res.json();
      setSavedNote(data.note);
    }
    setSaving(false);
  }, [siteId, note]);

  if (authLoading) return null;

  if (!user) {
    return (
      <p className="text-sm text-muted-foreground">
        <Link href="/login" className="text-accent hover:underline">
          Sign in
        </Link>{" "}
        to add a private note to this site.
      </p>
    );
  }

  if (fetchedFor !== `${user.id}:${siteId}`) {
    return <p className="text-sm text-muted-foreground">Loading&hellip;</p>;
  }

  const dirty = note !== savedNote;

  return (
    <div className="flex flex-col gap-2">
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={MAX_LENGTH}
        rows={3}
        placeholder="Private note, only visible to you..."
        className="w-full rounded-lg border border-border-color bg-surface-muted px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent resize-none"
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {note.length}/{MAX_LENGTH}
        </span>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={!dirty || saving}
          className="text-sm font-medium text-accent hover:underline disabled:opacity-50 disabled:no-underline"
        >
          {saving ? "Saving..." : dirty ? "Save note" : "Saved"}
        </button>
      </div>
    </div>
  );
}
