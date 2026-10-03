"use client";

import { useSyncExternalStore } from "react";

function subscribe(callback: () => void) {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

function getSnapshot() {
  return document.documentElement.classList.contains("dark");
}

// The anti-flash script in layout.tsx sets the real class before hydration;
// this is only the value assumed during the server-rendered HTML itself.
function getServerSnapshot() {
  return false;
}

function applyTheme(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
  localStorage.setItem("theme", dark ? "dark" : "light");
}

export default function ThemeToggle() {
  const isDark = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return (
    <button
      type="button"
      onClick={() => applyTheme(!isDark)}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border-color bg-surface text-foreground hover:bg-surface-muted transition-colors"
    >
      {isDark ? (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
          <path
            fillRule="evenodd"
            d="M12 2.25a.75.75 0 01.75.75v2a.75.75 0 01-1.5 0V3a.75.75 0 01.75-.75zM7.5 12a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM18.894 6.166a.75.75 0 00-1.06-1.06l-1.415 1.414a.75.75 0 101.06 1.06l1.415-1.414zM21.75 12a.75.75 0 01-.75.75h-2a.75.75 0 010-1.5h2a.75.75 0 01.75.75zM17.834 18.894a.75.75 0 001.06-1.06l-1.414-1.415a.75.75 0 10-1.06 1.06l1.414 1.415zM12 18a.75.75 0 01.75.75v2a.75.75 0 01-1.5 0v-2A.75.75 0 0112 18zM7.758 17.303a.75.75 0 00-1.061-1.06l-1.414 1.414a.75.75 0 001.06 1.06l1.415-1.414zM6 12a.75.75 0 01-.75.75h-2a.75.75 0 010-1.5h2A.75.75 0 016 12zM6.697 7.757a.75.75 0 001.06-1.06L6.343 5.282a.75.75 0 00-1.06 1.06l1.414 1.415z"
            clipRule="evenodd"
          />
        </svg>
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
          <path
            fillRule="evenodd"
            d="M9.528 1.718a.75.75 0 01.162.819A8.97 8.97 0 009 6a9 9 0 009 9 8.97 8.97 0 003.463-.69.75.75 0 01.981.98 10.503 10.503 0 01-9.694 6.46c-5.799 0-10.5-4.7-10.5-10.5 0-4.368 2.667-8.112 6.46-9.694a.75.75 0 01.818.162z"
            clipRule="evenodd"
          />
        </svg>
      )}
    </button>
  );
}
