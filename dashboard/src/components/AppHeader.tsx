import Link from "next/link";
import Logo from "@/components/Logo";
import ThemeToggle from "@/components/ThemeToggle";
import UserMenu from "@/components/UserMenu";

export default function AppHeader({ onMenuClick }: { onMenuClick: () => void }) {
  return (
    <header className="sticky top-0 z-10 border-b border-border-color bg-surface-muted/90 backdrop-blur">
      <div className="flex items-center justify-between px-4 sm:px-6 py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onMenuClick}
            aria-label="Toggle sites menu"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-border-color text-foreground hover:bg-surface md:hidden"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5M3.75 17.25h16.5" />
            </svg>
          </button>
          <Link href="/" className="flex items-center gap-2.5">
            <Logo size={32} />
            <div className="leading-tight">
              <p className="font-semibold text-foreground">OneAquaHealth</p>
              <p className="text-xs text-muted-foreground">Gowanus Canal, Brooklyn</p>
            </div>
          </Link>
        </div>
        <div className="flex items-center gap-3">
          <UserMenu />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
