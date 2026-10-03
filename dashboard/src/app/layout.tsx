import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import AppShell from "@/components/AppShell";
import { AuthProvider } from "@/lib/auth-context";
import { getSites, getOrderedSiteIds, getRiskSummaries } from "@/lib/data";
import type { SiteRiskSummary } from "@/lib/types";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "OneAquaHealth Dashboard",
  description: "Stream-health insight for the Gowanus Canal, from citizen observations.",
};

// Runs before hydration so the correct theme class is present on first
// paint -- otherwise the page would flash the wrong theme for a frame.
const THEME_INIT_SCRIPT = `
  (function () {
    try {
      var stored = localStorage.getItem("theme");
      var dark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.classList.toggle("dark", dark);
    } catch (e) {}
  })();
`;

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const sites = getSites();
  const orderedSiteIds = getOrderedSiteIds();
  const { data: riskSummaries } = await getRiskSummaries();
  const riskBySiteId = Object.fromEntries(
    riskSummaries.map((r) => [r.site_id, r])
  ) as Record<string, SiteRiskSummary>;

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <Script id="theme-init" strategy="beforeInteractive">
          {THEME_INIT_SCRIPT}
        </Script>
      </head>
      <body className="min-h-full">
        <AuthProvider>
          <AppShell sites={sites} orderedSiteIds={orderedSiteIds} riskBySiteId={riskBySiteId}>
            {children}
          </AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
