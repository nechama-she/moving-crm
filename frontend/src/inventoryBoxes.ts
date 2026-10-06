/** Boxes, bins, and totes share the inventory's Boxes total. */
export function isInventoryBox(name: string): boolean {
  if (/\bbox\s*springs?\b|\blitter\s*box\b|\b(?:tool|juke)\s*box\b/i.test(name)) return false;
  return /\b(?:box(?:es)?|bins?|totes?|cartons?)\b|\bdish\s*pack\b|\bbins(?=small\b)/i.test(name);
}
