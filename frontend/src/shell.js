import { createContext, useContext, useMemo } from "react";
import { shellNav } from "./nav.js";

export const ShellContext = createContext({
  me: null,
  health: null,
  counts: {},
  refreshCounts: () => {},
});

export const useShell = () => useContext(ShellContext);

// Keyed on `me`: the context value is a new object on every render.
export function useShellNav() {
  const { me } = useShell();
  return useMemo(() => shellNav(me), [me]);
}
