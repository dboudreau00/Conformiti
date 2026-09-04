import { twMerge } from "tailwind-merge";

/** Join class names, dropping falsy parts and resolving Tailwind conflicts. */
export function cn(...parts) {
  return twMerge(parts.filter(Boolean).join(" "));
}
