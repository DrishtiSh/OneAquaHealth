// Run a Python module with the repo's .venv interpreter (falls back to `python` on PATH), so
// `npm run snapshot` works on Windows and Unix without activating the venv first.
// Usage: node scripts/py.mjs -m pipeline.snapshot.freeze_snapshot
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const candidates = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")];
const python = candidates.find(existsSync) ?? "python";

const { status, error } = spawnSync(python, process.argv.slice(2), { cwd: root, stdio: "inherit" });
if (error) {
  console.error(`could not run ${python}: ${error.message}`);
  process.exit(1);
}
process.exit(status ?? 1);
