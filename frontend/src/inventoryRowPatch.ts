type Item = {id: string; catalog_item_id?: string; name_override?: boolean; name: string; cuft: number; quantity: number; going?: boolean; mover_pack?: boolean; reference_name?: string};
type Room = {id: string; room_type_id: string; name: string; items: Record<string, number>; item_names?: Record<string,string>; custom_items?: Item[]};
type CatalogItem = {id: string; name: string; cuft: number};
export type InventoryRowPatch = {
  room: string;
  expected: {name: string; cuft: number; quantity: number; going: boolean};
  changes: {name: string; cuft: number; quantity: number; going: boolean; name_override: boolean};
};

/** Detect one edited row; structural edits continue through the list endpoint. */
export function inventoryRowPatch(before: Room[] | null, after: Room[], catalog: CatalogItem[]): InventoryRowPatch | null {
  if (!before || before.length !== after.length) return null;
  const byId = new Map(catalog.map(item => [item.id, item]));
  const entries = (room: Room) => [
    ...Object.entries(room.items).filter(([,qty]) => qty > 0).map(([id, quantity]) => ({
      name: room.item_names?.[id] || byId.get(id)?.name || 'Item', cuft: byId.get(id)?.cuft || 0,
      quantity, going: true, name_override: !!room.item_names?.[id], mover_pack: undefined as boolean | undefined,
    })),
    ...(room.custom_items || []).map(item => ({name:item.name,cuft:item.cuft,quantity:item.quantity,
      going:item.going !== false,name_override:!!item.name_override,mover_pack:item.mover_pack})),
  ];
  let patch: InventoryRowPatch | null = null;
  for (let i=0;i<before.length;i++) {
    const oldRoom=before[i], newRoom=after[i];
    if (oldRoom.id!==newRoom.id || oldRoom.name!==newRoom.name || oldRoom.room_type_id!==newRoom.room_type_id) return null;
    const oldRows=entries(oldRoom), newRows=entries(newRoom);
    if (oldRows.length!==newRows.length) return null;
    // Catalog edits become custom rows and may move to the end of the array.
    const remaining=[...newRows];
    const changed=oldRows.filter(row=>{
      const index=remaining.findIndex(candidate=>JSON.stringify(candidate)===JSON.stringify(row));
      if(index<0)return true;
      remaining.splice(index,1);return false;
    });
    if(!changed.length)continue;
    if(patch || changed.length!==1 || remaining.length!==1 || changed[0].mover_pack!==remaining[0].mover_pack)return null;
    const {name,cuft,quantity,going}=changed[0];
    const updated=remaining[0];
    patch={room:oldRoom.name,expected:{name,cuft,quantity,going},changes:{
      name:updated.name,cuft:updated.cuft,quantity:updated.quantity,going:updated.going,name_override:updated.name_override,
    }};
  }
  return patch;
}
