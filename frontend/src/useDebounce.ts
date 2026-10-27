import { useEffect, useState } from "react";

// Returns `value` only after it stopped changing for `delayMs`.
// Typing "lamp" then sends one search, not four ("l", "la", "lam", "lamp").
export function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
