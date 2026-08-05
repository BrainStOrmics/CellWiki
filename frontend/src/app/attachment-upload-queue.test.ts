import { describe, expect, it } from "vitest";

import { appendAsyncTask } from "./attachment-upload-queue";

describe("attachment upload queue", () => {
  it("serializes multiple file selections and continues after a failed upload", async () => {
    const calls: string[] = [];
    let releaseFirst!: () => void;
    const firstStarted = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });

    const first = appendAsyncTask(null, async () => {
      calls.push("first:start");
      await firstStarted;
      calls.push("first:end");
      throw new Error("first upload failed");
    });
    const second = appendAsyncTask(first, async () => {
      calls.push("second:start");
      calls.push("second:end");
    });

    await Promise.resolve();
    await Promise.resolve();
    expect(calls).toEqual(["first:start"]);

    releaseFirst();
    await expect(first).rejects.toThrow("first upload failed");
    await second;

    expect(calls).toEqual([
      "first:start",
      "first:end",
      "second:start",
      "second:end",
    ]);
  });
});
