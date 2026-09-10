import { useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Bot, ExternalLink, FileSearch, GitPullRequestDraft } from "lucide-react";
import { useI18n } from "../../i18n";

type MarkdownReaderProps = {
  markdown: string;
  /** 页头已经渲染的文档标题；正文首个 H1 与它重复时不再渲染第二个大标题。 */
  title?: string;
  onWikiLink?: (pageId: string) => void;
  onAskSelection?: (text: string) => void;
  onCheckEvidence?: (text: string) => void;
  onProposeRevision?: (text: string) => void;
};

type SelectionMenu = { text: string; x: number; y: number };

/**
 * Internal navigation targets: [[wikilinks]] become /wiki/<id> above, and the exported
 * pages also cross-link each other with relative `sibling.md` hrefs. Both must stay in
 * the reader instead of opening a browser, so they resolve to a page id.
 */
export function wikiTargetFor(href?: string): string | null {
  if (!href || href.startsWith("#") || href.startsWith("//")) return null;
  if (href.startsWith("/wiki/")) return decodePageId(href.slice("/wiki/".length));
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return null;
  const path = href.split("#")[0];
  return path.toLowerCase().endsWith(".md")
    ? decodePageId(path.slice(0, -3).split("/").pop() ?? "")
    : null;
}

/** Page ids come from user-editable Markdown, so a broken escape must not blank the reader. */
function decodePageId(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function wikiLinks(markdown: string): string {
  return markdown.replace(
    /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
    (_, target: string, label?: string) => `[${label || target}](/wiki/${encodeURIComponent(target.trim())})`,
  );
}

/** The first ATX heading of a page, or null when the body opens with prose. */
export function leadingHeading(markdown: string): string | null {
  const heading = /^\s*#\s+([^\n]*)/.exec(markdown);
  return heading ? heading[1] : null;
}

export function sameHeadingText(left: string, right: string): boolean {
  return left.trim().toLocaleLowerCase() === right.trim().toLocaleLowerCase();
}

/**
 * A page gets exactly one title. When its first H1 repeats the display name the shell
 * header keeps it and the body heading is dropped; otherwise the body heading wins and
 * the caller must not render a header (see AppShell).
 */
function stripDuplicateTitle(markdown: string, title?: string): string {
  if (!title) return markdown;
  const heading = /^\s*#\s+([^\n]*)\n+/.exec(markdown);
  if (!heading || !sameHeadingText(heading[1], title)) return markdown;
  return markdown.slice(heading[0].length);
}

function textContent(children: ReactNode): string {
  if (Array.isArray(children)) return children.map(textContent).join("");
  return typeof children === "string" || typeof children === "number" ? String(children) : "";
}

function slug(children: ReactNode): string {
  return textContent(children)
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/(^-|-$)/g, "");
}

export function MarkdownReader({
  markdown,
  title,
  onWikiLink,
  onAskSelection,
  onCheckEvidence,
  onProposeRevision,
}: MarkdownReaderProps) {
  const { t } = useI18n();
  const rootRef = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState<SelectionMenu | null>(null);
  const rendered = useMemo(() => wikiLinks(stripDuplicateTitle(markdown, title)), [markdown, title]);

  function captureSelection(event: MouseEvent<HTMLDivElement>) {
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? "";
    const root = rootRef.current;
    if (!text || !selection || !root || !selection.anchorNode || !root.contains(selection.anchorNode)) {
      setMenu(null);
      return;
    }
    const bounds = root.getBoundingClientRect();
    setMenu({
      text: text.slice(0, 4000),
      x: Math.min(event.clientX - bounds.left, Math.max(20, bounds.width - 260)),
      y: event.clientY - bounds.top + root.scrollTop,
    });
  }

  function act(callback: ((text: string) => void) | undefined) {
    if (menu && callback) callback(menu.text);
    setMenu(null);
  }

  return (
    <div className="formal-markdown-reader" ref={rootRef} onMouseUp={captureSelection}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          h1: ({ children }) => <h1 id={slug(children)}>{children}</h1>,
          h2: ({ children }) => {
            const heading = textContent(children);
            const curated = /curat|人工|编者/i.test(heading);
            return <h2 id={slug(children)} data-origin={curated ? "curation" : "generated"}>{children}</h2>;
          },
          h3: ({ children }) => <h3 id={slug(children)}>{children}</h3>,
          a: ({ href, children }) => {
            const pageId = wikiTargetFor(href);
            if (pageId) {
              return <button className="wiki-inline-link" onClick={() => onWikiLink?.(pageId)}>{children}</button>;
            }
            return <a href={href} target="_blank" rel="noreferrer">{children}<ExternalLink size={11} /></a>;
          },
          table: ({ children }) => <div className="markdown-table-wrap"><table>{children}</table></div>,
        }}
      >
        {rendered}
      </ReactMarkdown>

      {menu && (
        <div className="selection-actions" style={{ left: menu.x, top: menu.y }}>
          <button onMouseDown={(event) => event.preventDefault()} onClick={() => act(onAskSelection)}>
            <Bot size={13} />{t("selection.ask")}
          </button>
          <button onMouseDown={(event) => event.preventDefault()} onClick={() => act(onCheckEvidence)}>
            <FileSearch size={13} />{t("selection.evidence")}
          </button>
          <button onMouseDown={(event) => event.preventDefault()} onClick={() => act(onProposeRevision)}>
            <GitPullRequestDraft size={13} />{t("selection.revise")}
          </button>
        </div>
      )}
    </div>
  );
}

