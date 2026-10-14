/** Display grouping only; never changes packing choices or saved inventory. */
export function isInventoryBox(name: string): boolean {
  if (/\bbox\s*springs?\b|\blitter\b|\b(?:bookshelf|bookcase|cabinet|dresser|shelving)\b/i.test(name)) return false;
  return /\bbox(?:es)?\b|\bbins?\b|\bbinssmall\b|\btotes?\b|\bsuit\s*cases?\b|\bduff(?:el|le)\s*bags?\b|\bamazon\s+bags?\b|\b(?:moving|storage|packing|garment)\s+bags?\b|\bluggage\b|\bdish\s*packs?\b|\bcartons?\b/i.test(name);
}

export function boxQuantity(name: string, quantity: number): number {
  return isInventoryBox(name) ? quantity : 0;
}
