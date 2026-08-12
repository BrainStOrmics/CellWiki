import type { AgentAttachmentReference, AttachmentRecord } from "../types";

/** Resolve message-level metadata from the upload result, independent of React render timing. */
export function attachmentReferencesForIds(
  records: AttachmentRecord[],
  attachmentIds: string[],
): AgentAttachmentReference[] {
  const recordsById = new Map(records.map((record) => [record.attachment_id, record]));
  return attachmentIds.map((attachmentId) => {
    const record = recordsById.get(attachmentId);
    return record
      ? {
        attachment_id: record.attachment_id,
        original_name: record.original_name,
        media_type: record.media_type,
        content_hash: record.content_hash,
        size_bytes: record.size_bytes,
      }
      : { attachment_id: attachmentId };
  });
}

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
