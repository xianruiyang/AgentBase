import { alpha } from "../a";

export function beta(): string {
  return alpha("nested");
}

export const sharedName = "nested";
