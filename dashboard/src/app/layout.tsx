import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import AppShell from "@/components/AppShell";
import DataFooter from "@/components/DataFooter";
import { AuthProvider } from "@/lib/auth-context";
import { getScenarioOptions, getSiteData } from "@/lib/data";
import { getScenario } from "@/lib/scenario";
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
  const scenario = await getScenario();
  const [siteData, scenarioOptions] = await Promise.all([
    getSiteData(scenario.variant, scenario.sensitivity),
    getScenarioOptions(),
  ]);

  return (
    // THEME_INIT_SCRIPT adds the "dark" class before React hydrates, so the class list is
    // expected to differ from the server render on this one element.
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <Script id="theme-init" strategy="beforeInteractive">
          {THEME_INIT_SCRIPT}
        </Script>
      </head>
      <body className="min-h-full">
        <AuthProvider>
          <AppShell
            sites={siteData.sites}
            orderedSiteIds={siteData.orderedSiteIds}
            riskBySiteId={siteData.riskBySiteId}
            scenario={scenario}
            scenarioOptions={scenarioOptions}
            footer={<DataFooter provenance={siteData} />}
          >
            {children}
          </AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
