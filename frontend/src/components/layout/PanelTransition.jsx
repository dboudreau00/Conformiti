import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { NAV_LOOKUP } from "../../nav.js";
import { cn } from "../../utils/cn.js";

export const EASE = [0.23, 1, 0.32, 1];

const PRODUCT = "Conformiti";
const SEP = " · ";

// What an add-on that renamed the product (white label) put in the tab, learned the first time it is seen after a page
// of ours, and the page name this component last wrote. Together they let a later page keep following the brand.
let brand = null;
let lastPage = null;

/** The product name in the current tab title, or null when the title is not ours to change. */
function productInTab() {
  const now = document.title;
  const carries = (name) => now === name || now.endsWith(SEP + name);
  if (carries(PRODUCT)) return PRODUCT;
  if (brand && carries(brand)) return brand;
  if (lastPage && now.startsWith(lastPage + SEP)) {
    brand = now.slice(lastPage.length + SEP.length);
    return brand;
  }
  return null;
}

export function PanelTransition({ children, className }) {
  const meta = NAV_LOOKUP[useLocation().pathname];
  const title = meta?.title;
  useEffect(() => {
    if (!title) return undefined;
    // A title that is neither the stock one nor an add-on's rename of it belongs to someone else: leave it.
    const product = productInTab();
    if (product === null) return undefined;
    const named = `${title}${SEP}${product}`;
    document.title = named;
    lastPage = title;
    return () => { if (document.title === named) document.title = product; };
  }, [title]);
  return (
    <motion.main
      id="main"
      tabIndex={-1}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.24, ease: EASE }}
      className={cn("mx-auto w-full max-w-[1680px] px-6 outline-none", meta ? "pb-6 pt-4" : "py-6", className)}
    >
      {meta ? (
        <div className="mb-4 flex flex-wrap items-baseline gap-x-3.5 gap-y-0.5">
          <h1 className="text-[22px] font-semibold leading-7 tracking-[-0.02em] text-ink">{meta.title}</h1>
        </div>
      ) : null}
      {children}
    </motion.main>
  );
}

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
