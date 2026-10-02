import { createContext, useContext, useMemo } from "react";
import { shellNav } from "./nav.js";

/** Data every page can read without refetching: the signed-in user, the
 * health/version record, and the live counters shown as nav badges. */
export const ShellContext = createContext({
  me: null,
  health: null,
  counts: {},
  refreshCounts: () => {},
});

export const useShell = () => useContext(ShellContext);

/** What the nav draws for this person, placed by section (see nav.js). The
 * context value is a new object on every render, so this keys on `me`. */
export function useShellNav() {
  const { me } = useShell();
  return useMemo(() => shellNav(me), [me]);
}
