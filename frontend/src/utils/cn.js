import { twMerge } from "tailwind-merge";

export function cn(...parts) {
  return twMerge(parts.filter(Boolean).join(" "));
}
