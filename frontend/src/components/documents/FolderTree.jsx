import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ChevronRightIcon, FolderIcon, FolderOpenIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";

function flatten(nodes, expanded, depth = 0, parentId = null, out = []) {
  for (const node of nodes) {
    const has = node.children?.length > 0;
    const open = has && expanded.has(node.id);
    out.push({ node, depth, parentId, has, open });
    if (open) flatten(node.children, expanded, depth + 1, node.id, out);
  }
  return out;
}

/** Renders whatever the API returns as roots: a folder whose parent this user cannot see is a root of their view. */
export function FolderTree({ nodes, selectedId, expanded, onToggle, onSelect, className, label = "Folders" }) {
  const rows = useMemo(() => flatten(nodes, expanded), [nodes, expanded]);
  const refs = useRef(new Map());
  const [activeId, setActiveId] = useState(null);

  const visible = rows.map((r) => r.node.id);
  const tabId = visible.includes(activeId) ? activeId : visible.includes(selectedId) ? selectedId : visible[0];

  function focusRow(id) {
    setActiveId(id);
    refs.current.get(id)?.focus();
  }

  function onKeyDown(e, row, index) {
    const { node, has, open, parentId } = row;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (rows[index + 1]) focusRow(rows[index + 1].node.id);
        break;
      case "ArrowUp":
        e.preventDefault();
        if (rows[index - 1]) focusRow(rows[index - 1].node.id);
        break;
      case "ArrowRight":
        e.preventDefault();
        if (has && !open) onToggle(node.id, true);
        else if (has && open && rows[index + 1]) focusRow(rows[index + 1].node.id);
        break;
      case "ArrowLeft":
        e.preventDefault();
        if (has && open) onToggle(node.id, false);
        else if (parentId != null) focusRow(parentId);
        break;
      case "Home":
        e.preventDefault();
        if (rows[0]) focusRow(rows[0].node.id);
        break;
      case "End":
        e.preventDefault();
        if (rows.length) focusRow(rows[rows.length - 1].node.id);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        onSelect(node);
        break;
      default:
    }
  }

  return (
    <ul role="tree" aria-label={label} className={cn("p-2", className)}>
      {rows.map((row, i) => {
        const { node, depth, has, open } = row;
        const selected = node.id === selectedId;
        return (
          <li
            key={node.id}
            ref={(el) => {
              if (el) refs.current.set(node.id, el);
              else refs.current.delete(node.id);
            }}
            role="treeitem"
            aria-level={depth + 1}
            aria-selected={selected}
            aria-expanded={has ? open : undefined}
            tabIndex={node.id === tabId ? 0 : -1}
            onFocus={() => setActiveId(node.id)}
            onClick={() => {
              onSelect(node);
              if (has && !open) onToggle(node.id, true);
            }}
            onKeyDown={(e) => onKeyDown(e, row, i)}
            title={node.name}
            className={cn(
              "relative flex cursor-pointer select-none items-center gap-2 rounded-lg py-1.5 pr-2.5 text-left",
              "transition-colors duration-150 ease-out",
              selected ? "text-accent" : "text-muted hover:bg-surface-2 hover:text-ink"
            )}
            style={{ paddingLeft: 6 + depth * 14 }}
          >
            {selected ? (
              <motion.span
                layoutId="folder-active"
                className="absolute inset-0 rounded-lg bg-accent/[0.07]"
                transition={{ type: "spring", stiffness: 520, damping: 38 }}
                aria-hidden="true"
              />
            ) : null}
            {/* Mouse-only: out of the tab order and hidden from AT; the keyboard expands with ArrowRight/ArrowLeft. */}
            {has ? (
              <button
                type="button"
                tabIndex={-1}
                aria-hidden="true"
                className="relative flex h-6 w-6 shrink-0 items-center justify-center rounded text-faint transition-colors duration-150 ease-out hover:bg-line-strong/30 hover:text-ink"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggle(node.id, !open);
                }}
              >
                <ChevronRightIcon
                  className={cn("h-3.5 w-3.5 transition-transform duration-150 ease-out", open && "rotate-90")}
                  strokeWidth={2}
                />
              </button>
            ) : (
              <span className="relative h-6 w-6 shrink-0" aria-hidden="true" />
            )}
            {open ? (
              <FolderOpenIcon className="relative h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
            ) : (
              <FolderIcon className="relative h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
            )}
            <span className="relative min-w-0 flex-1 truncate text-[13px] font-medium">{node.name}</span>
            {node.document_count > 0 ? (
              <span className="tabular relative font-mono text-2xs text-faint">{node.document_count}</span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
