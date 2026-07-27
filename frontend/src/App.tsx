import { AppShell } from "./app/AppShell";

/** The public entry stays intentionally shallow; product features live behind AppShell. */
export function App() {
  return <AppShell />;
}
