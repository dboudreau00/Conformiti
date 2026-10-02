import { useEffect } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

/**
 * Lets a link open a page already filtered: the search box, the dashboard and
 * the control cards link to /controls?framework=...&search=..., and the page
 * seeds its own state from that address.
 *
 * `apply` receives the address's URLSearchParams when the page is entered and
 * again each time a link arrives, including a link to the address the page is
 * already at (the location key changes, the query string need not). It is not
 * called when the reader later changes a filter, so the page's own state is
 * never overwritten by an address that has gone stale.
 */
export function useDeepLink(apply) {
  const { key } = useLocation();
  const [params] = useSearchParams();
  useEffect(() => {
    apply(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
