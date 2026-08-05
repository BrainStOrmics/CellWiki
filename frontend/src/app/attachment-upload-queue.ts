/**
 * Append one asynchronous upload to a previous upload without allowing a
 * failed upload to block later file selections.
 */
export function appendAsyncTask(
  previous: Promise<void> | null,
  task: () => Promise<void>,
): Promise<void> {
  return (previous ?? Promise.resolve())
    .catch(() => undefined)
    .then(task);
}
