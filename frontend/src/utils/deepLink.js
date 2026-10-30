import { useEffect } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

/** `apply(URLSearchParams)` runs on entry and on every arriving link, even one to the current address; never when the
 * reader changes a filter, so a stale address cannot overwrite the page's own state. */
export function useDeepLink(apply) {
  const { key } = useLocation();
  const [params] = useSearchParams();
  useEffect(() => {
    apply(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
