import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";

export const EASE = [0.23, 1, 0.32, 1];

/** Wraps a routed page. Enters after the previous page has left (AnimatePresence mode="wait"). */
export function PanelTransition({ children, className }) {
  return (
    <motion.main
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.24, ease: EASE }}
      className={cn("mx-auto w-full max-w-[1680px] px-6 py-6", className)}
    >
      {children}
    </motion.main>
  );
}

/** Staggers the top-level blocks of a page so the layout resolves rather than popping. */
export const stack = {
  container: { hidden: {}, show: { transition: { staggerChildren: 0.045, delayChildren: 0.02 } } },
  item: { hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: { duration: 0.26, ease: EASE } } },
};

export function Stack({ children, className }) {
  return (
    <motion.div variants={stack.container} initial="hidden" animate="show" className={className}>
      {children}
    </motion.div>
  );
}

export function StackItem({ children, className }) {
  return (
    <motion.div variants={stack.item} className={className}>
      {children}
    </motion.div>
  );
}

/** Height-animated disclosure region (expanding table rows, drawers). */
export function Collapse({ open, children, className }) {
  return open ? (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.22, ease: EASE }}
      className={cn("overflow-hidden", className)}
    >
      {children}
    </motion.div>
  ) : null;
}
