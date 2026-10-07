type Item = {id:string;catalog_item_id?:string|null;name_override?:boolean;name:string;cuft:number;quantity:number;going?:boolean;mover_pack?:boolean|null;unit_weight?:number};
type Room = {id:string;room_type_id:string;name:string;items:Record<string,number>;item_names?:Record<string,string>;custom_items?:Item[]};
type CatalogItem = {id:string;name:string;cuft:number;weight?:number};
type Values = {room_id:string;name:string|null;quantity:number;cuft:number;going:boolean;mover_pack:boolean|null};
type Add = Omit<Values,'name'> & {id:string;name?:string;catalog_item_id?:string;unit_weight?:number};
export type InventoryEdits = {update:{id:string;fields:Partial<Values>}[];delete:string[];add:Add[];rooms:{update:{id:string;name:string}[];delete:string[];add:{id:string;name:string;room_type_id:string}[]}};
const catalogIds = new Map<string,string>();
export function catalogInventoryId(room:Room,id:string):string {
  const key = `${room.id}:${id}`;
  if (!catalogIds.has(key)) catalogIds.set(key,crypto.randomUUID());
  return catalogIds.get(key)!;
}
const baseName = (name:string) => name.replace(/\s*\((?:CP|PBO)\)\s*$/i,'').trim();
export function inventoryActions(before:Room[],after:Room[],catalog:CatalogItem[]):InventoryEdits {
  const lookup = new Map(catalog.map(item=>[item.id,item]));
  const flatten = (rooms:Room[]) => new Map(rooms.flatMap(room=>[
    ...Object.entries(room.items).filter(([,qty])=>qty>0).map(([id,quantity])=>({id:catalogInventoryId(room,id),catalog_item_id:id,
      name:room.item_names?.[id]||lookup.get(id)?.name||'Item',name_override:!!room.item_names?.[id],quantity,cuft:lookup.get(id)?.cuft||0,
      unit_weight:lookup.get(id)?.weight||0,room_id:room.id})),
    ...(room.custom_items||[]).map(item=>({...item,room_id:room.id})),
  ].map(item=>[item.id,item] as const)));
  const previous=flatten(before), current=flatten(after);
  const edits:InventoryEdits={update:[],delete:[],add:[],rooms:{update:[],delete:[],add:[]}};
  const oldRooms=new Map(before.map(room=>[room.id,room])), newRooms=new Map(after.map(room=>[room.id,room]));
  for(const room of before) {
    const next=newRooms.get(room.id);
    if(!next) edits.rooms.delete.push(room.id);
    else if(next.name!==room.name) edits.rooms.update.push({id:room.id,name:next.name});
  }
  for(const room of after) if(!oldRooms.has(room.id)) edits.rooms.add.push({id:room.id,name:room.name,room_type_id:room.room_type_id});
  const values=(item:Item & {room_id:string}):Values=>({room_id:item.room_id,
    name:!item.catalog_item_id||item.name_override?baseName(item.name):null,
    quantity:item.quantity,cuft:item.cuft,going:item.going!==false,
    mover_pack:item.mover_pack??(/\((?:CP|PBO)\)\s*$/i.test(item.name)?/\(CP\)\s*$/i.test(item.name):null)});
  for(const [id,item] of previous) {
    if(edits.rooms.delete.includes(item.room_id)) continue;
    const next=current.get(id);
    if(!next) {edits.delete.push(id);continue;}
    const oldValue=values(item), newValue=values(next), fields:Partial<Values>={};
    for(const field of Object.keys(newValue) as (keyof Values)[]) if(oldValue[field]!==newValue[field]) Object.assign(fields,{[field]:newValue[field]});
    if(Object.keys(fields).length) edits.update.push({id,fields});
  }
  for(const [id,item] of current) if(!previous.has(id)) {
    const {name,...value}=values(item);
    edits.add.push({id,...value,...(name!==null?{name}:{}),...(item.catalog_item_id?{catalog_item_id:item.catalog_item_id}:{}),unit_weight:item.unit_weight||0});
  }
  return edits;
}
export const hasInventoryEdits=(edits:InventoryEdits)=>Object.values(edits.rooms).some(list=>list.length>0)||edits.update.length>0||edits.delete.length>0||edits.add.length>0;
