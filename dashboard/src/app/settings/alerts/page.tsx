import { getSiteData } from "@/lib/data";
import { getScenario } from "@/lib/scenario";
import AlertPreferencesForm from "@/components/AlertPreferencesForm";

export default async function AlertSettingsPage() {
  const scenario = await getScenario();
  const { sites } = await getSiteData(scenario.variant, scenario.sensitivity);

  return (
    <main className="flex flex-1 flex-col gap-6 max-w-3xl mx-auto w-full px-6 py-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Alert preferences
        </h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-xl">
          Choose which sites you&apos;d want to hear about. Detection results now come from the
          Insight API, but sending notifications isn&apos;t built yet &mdash; these preferences are
          saved and ready for when it is.
        </p>
      </header>
      <AlertPreferencesForm sites={sites} />
    </main>
  );
}
