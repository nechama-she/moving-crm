type LinkedItem = {catalog_item_id?: string; quantity: number};
type InventoryRoom<T extends LinkedItem> = {items: Record<string, number>; custom_items?: T[]};

export function catalogQuantity<T extends LinkedItem>(room: InventoryRoom<T>, id: string): number {
  return (room.items[id] || 0) + (room.custom_items || []).reduce(
    (sum, item) => sum + (item.catalog_item_id === id ? item.quantity : 0), 0);
}

export function setCatalogQuantity<T extends LinkedItem, R extends InventoryRoom<T>>(room: R, id: string, value: number): R {
  const target = Math.max(0, Math.min(999, Math.floor(Number.isFinite(value) ? value : 0)));
  const delta = target - catalogQuantity(room, id);
  const items = {...room.items};
  // New units use the catalog entry; existing custom measurements and packing
  // choices remain attached to their original units.
  if (delta >= 0) return {...room, items: {...items, [id]: (items[id] || 0) + delta}};
  let remove = -delta;
  const fromCatalog = Math.min(items[id] || 0, remove);
  items[id] = (items[id] || 0) - fromCatalog;
  remove -= fromCatalog;
  const custom_items = (room.custom_items || []).flatMap(item => {
    if (item.catalog_item_id !== id || remove === 0) return [item];
    const reduction = Math.min(item.quantity, remove);
    remove -= reduction;
    return item.quantity > reduction ? [{...item, quantity: item.quantity - reduction}] : [];
  });
  return {...room, items, custom_items};
}
