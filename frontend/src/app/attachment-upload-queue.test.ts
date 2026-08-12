import { describe, expect, it } from "vitest";

import type { AttachmentRecord } from "../types";
import { appendAsyncTask, attachmentReferencesForIds } from "./attachment-upload-queue";

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

  it("keeps uploaded metadata when a message sends before React state commits", () => {
    const attachment: AttachmentRecord = {
      attachment_id: "att_" + "a".repeat(32),
      thread_id: "thread_" + "b".repeat(32),
      original_name: "paper.pdf",
      media_type: "application/pdf",
      size_bytes: 42,
      content_hash: "sha256:" + "c".repeat(64),
      created_at: "2026-01-01T00:00:00Z",
    };

    expect(attachmentReferencesForIds([attachment], [attachment.attachment_id])).toEqual([{
      attachment_id: attachment.attachment_id,
      original_name: "paper.pdf",
      media_type: "application/pdf",
      content_hash: attachment.content_hash,
      size_bytes: 42,
    }]);
  });
});
