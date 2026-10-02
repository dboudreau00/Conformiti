/** First tab stop on every shell page: jumps past the bar to the page's <main>.
 * It focuses the element instead of following the hash, so the address bar
 * does not gain "#main" and the router is not asked about it. */
export function SkipLink() {
  return (
    <a
      href="#main"
      onClick={(e) => {
        const main = document.getElementById("main");
        if (!main) return;
        e.preventDefault();
        main.focus();
      }}
      className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-[13px] focus:font-semibold focus:text-accent-ink"
    >
      Skip to content
    </a>
  );
}
