import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, File, FileCode, FileText, Folder, FolderOpen } from "lucide-react";
import { getJson } from "../../lib/product-api";

export type WorkspaceTreeEntry = {
  name: string;
  path: string;
  kind: "dir" | "file";
  type: "dir" | "md" | "txt" | "pdf" | "binary";
  size?: number | null;
};

export type WorkspaceTreeNode = WorkspaceTreeEntry & { children?: WorkspaceTreeNode[] };

export function fileIcon(entry: WorkspaceTreeEntry) {
  if (entry.type === "txt") return <FileCode size={14} />;
  if (entry.type === "pdf") return <File size={14} />;
  return <FileText size={14} />;
}

/**
 * 将扁平的工作区条目列表构建为嵌套树：目录在前、同级按名称自然排序。
 * Obsidian 式侧边栏文件树的纯函数核心，可单测。
 */
export function buildTree(entries: WorkspaceTreeEntry[] | null | undefined): WorkspaceTreeNode[] {
  const nodes = new Map<string, WorkspaceTreeNode>();
  for (const entry of entries ?? []) {
    const node: WorkspaceTreeNode =
      entry.kind === "dir" ? { ...entry, children: [] } : { ...entry }
    nodes.set(node.path, node);
  }
  // 补齐缺失的中间目录，保证任意层级都能挂到根（Obsidian 树层级完整）
  for (const path of Array.from(nodes.keys())) {
    const parts = path.split("/");
    for (let i = 1; i < parts.length; i += 1) {
      const parentPath = parts.slice(0, i).join("/");
      if (!nodes.has(parentPath)) {
        nodes.set(parentPath, {
          name: parts[i - 1],
          path: parentPath,
          kind: "dir",
          type: "dir",
          size: null,
          children: [],
        });
      }
    }
  }
  const roots: WorkspaceTreeNode[] = [];
  for (const node of nodes.values()) {
    const slash = node.path.lastIndexOf("/");
    if (slash === -1) {
      roots.push(node);
    } else {
      const parent = nodes.get(node.path.slice(0, slash));
      if (parent && parent.children) parent.children.push(node);
      else roots.push(node);
    }
  }
  const sortNodes = (list: WorkspaceTreeNode[]) => {
    list.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
    });
    for (const node of list) if (node.children) sortNodes(node.children);
  };
  sortNodes(roots);
  return roots;
}

/**
 * 按名称过滤树：保留匹配的节点（目录命中时保留整棵子树），非目录命中时保留祖先链。
 */
export function filterTree(nodes: WorkspaceTreeNode[], needle: string): WorkspaceTreeNode[] {
  if (!needle) return nodes;
  const kept: WorkspaceTreeNode[] = [];
  for (const node of nodes) {
    const selfMatch = node.name.toLowerCase().includes(needle);
    const children = node.children ? filterTree(node.children, needle) : [];
    if (selfMatch && node.kind === "dir") {
      kept.push({ ...node, children: node.children });
    } else if (selfMatch || children.length > 0) {
      kept.push({ ...node, children: children.length > 0 ? children : undefined });
    }
  }
  return kept;
}

type Props = {
  filter?: string;
  selectedPath?: string | null;
  onOpenFile?: (entry: WorkspaceTreeEntry) => void;
  refreshSignal?: number;
};

export function WorkspaceFileBrowser({ filter = "", selectedPath = null, onOpenFile, refreshSignal = 0 }: Props) {
  const [entries, setEntries] = useState<WorkspaceTreeEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ wiki: true });

  useEffect(() => {
    getJson<WorkspaceTreeEntry[]>("/api/workspace/tree")
      .then((next) => {
        setError(null);
        setEntries(next);
      })
      .catch((cause) => {
        // 刷新失败时保留已加载的树，只在首次加载失败时显示错误
        if (entries === null) setError(String(cause));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  const needle = filter.trim().toLowerCase();
  const filterActive = needle.length > 0;
  const tree = useMemo(() => {
    const roots = buildTree(entries);
    return filterActive ? filterTree(roots, needle) : roots;
  }, [entries, filterActive, needle]);

  function toggle(path: string) {
    setExpanded((current) => ({ ...current, [path]: !current[path] }));
  }

  function renderNode(node: WorkspaceTreeNode, depth: number) {
    if (node.kind === "dir") {
      const open = filterActive || Boolean(expanded[node.path]);
      return (
        <div key={node.path}>
          <button
            className="tree-folder-row"
            style={{ paddingLeft: 10 + depth * 14 }}
            onClick={() => toggle(node.path)}
            title={node.path}
          >
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {open ? <FolderOpen size={14} /> : <Folder size={14} />}
            <span>{node.name}</span>
          </button>
          {open && (node.children ?? []).map((child) => renderNode(child, depth + 1))}
        </div>
      );
    }
    const selected = selectedPath === node.path;
    return (
      <button
        key={node.path}
        className={selected ? "tree-file selected" : "tree-file"}
        style={{ paddingLeft: 24 + depth * 14 }}
        onClick={() => onOpenFile?.(node)}
        title={node.path}
      >
        {fileIcon(node)}
        <span>{node.name}</span>
      </button>
    );
  }

  if (error) return <div className="tree-empty">工作区文件加载失败: {error}</div>;
  if (!entries) return <div className="tree-empty">加载中…</div>;
  if (tree.length === 0) return <div className="tree-empty">{filterActive ? "无匹配文件" : "工作区为空"}</div>;

  return <div className="workspace-tree">{tree.map((node) => renderNode(node, 0))}</div>;
}
