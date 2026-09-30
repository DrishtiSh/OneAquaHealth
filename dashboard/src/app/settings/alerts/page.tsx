import { getSites } from "@/lib/data";
import AlertPreferencesForm from "@/components/AlertPreferencesForm";

export default function AlertSettingsPage() {
  const sites = getSites();

  return (
    <main className="flex flex-1 flex-col gap-6 max-w-3xl mx-auto w-full px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Alert preferences
        </h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-xl">
          Choose which sites you&apos;d want to hear about. Sending real notifications needs the
          detection backend (Stages 5-9), which isn&apos;t built yet &mdash; these preferences are
          saved now and ready for when it is.
        </p>
      </header>
      <AlertPreferencesForm sites={sites} />
    </main>
  );
}
