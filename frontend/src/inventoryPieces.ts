/** Explicit piece counts in item names; otherwise one piece per inventory unit. */
export function piecesPerItem(name: string): number {
  const match = name.match(/\b(\d+)\s*[-–—]?\s*pieces?\b/i);
  const pieces = match ? Number(match[1]) : 1;
  return Number.isSafeInteger(pieces) && pieces > 0 ? pieces : 1;
}
