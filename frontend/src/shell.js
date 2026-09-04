import { createContext, useContext } from "react";

/** Data every page can read without refetching: the signed-in user, the
 * health/version record, and the live counters shown as sidebar badges. */
export const ShellContext = createContext({
  me: null,
  health: null,
  counts: {},
  refreshCounts: () => {},
});

export const useShell = () => useContext(ShellContext);
