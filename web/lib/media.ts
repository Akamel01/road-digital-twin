import { useSyncExternalStore } from "react";

// Breakpoints from issue #11: phone under 768 px, tablet 768 to 1279 px, desktop 1280 px and up.
export const PHONE = "(max-width: 767px)";
export const TABLET = "(min-width: 768px) and (max-width: 1279px)";

/** True while the query matches. The server render sees false, then the client catches up after hydration. */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
