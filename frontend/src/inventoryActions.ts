type Item = {id:string;catalog_item_id?:string;name_override?:boolean;name:string;cuft:number;quantity:number;going?:boolean;mover_pack?:boolean;reference_name?:string};
type Room = {id:string;room_type_id:string;name:string;items:Record<string,number>;item_names?:Record<string,string>;custom_items?:Item[]};
type CatalogItem = {id:string;name:string;cuft:number;weight?:number};
type Row = {name:string;cuft:number;quantity:number;going:boolean;name_override:boolean;catalog_item_id?:string;mover_pack?:boolean;reference_name?:string;unit_weight:number};
export type InventoryAction = {kind:'room_add'|'room_remove'|'room_rename'|'row_add'|'row_remove'|'row_update';room:string;room_type_id?:string;name?:string;expected?:Row;value?:Row};
export function inventoryActions(before:Room[], after:Room[], catalog:CatalogItem[]):InventoryAction[] {
  const lookup=new Map(catalog.map(item=>[item.id,item]));
  const rows=(room:Room):Row[]=>[
    ...Object.entries(room.items).filter(([,n])=>n>0).map(([id,quantity])=>({name:room.item_names?.[id]||lookup.get(id)?.name||'Item',
      cuft:lookup.get(id)?.cuft||0,quantity,going:true,name_override:!!room.item_names?.[id],catalog_item_id:id,unit_weight:lookup.get(id)?.weight||0})),
    ...(room.custom_items||[]).map(item=>({name:item.name,cuft:item.cuft,quantity:item.quantity,going:item.going!==false,
      name_override:!!item.name_override,catalog_item_id:item.catalog_item_id,mover_pack:item.mover_pack,reference_name:item.reference_name,unit_weight:0})),
  ];
  const signature=(row:Row)=>JSON.stringify([row.name,row.cuft,row.quantity,row.going,row.name_override,row.catalog_item_id,row.mover_pack]);
  const actions:InventoryAction[]=[];
  const used=new Set<string>();
  for(const old of before){
    const next=after.find(room=>room.id===old.id)||after.find(room=>room.name===old.name&&!used.has(room.id));
    if(!next){actions.push({kind:'room_remove',room:old.name});continue;}
    used.add(next.id);
    if(old.name!==next.name)actions.push({kind:'room_rename',room:old.name,name:next.name,room_type_id:next.room_type_id});
    const remaining=rows(next);
    const removed=rows(old).filter(row=>{const index=remaining.findIndex(other=>signature(other)===signature(row));if(index<0)return true;remaining.splice(index,1);return false;});
    for(const expected of removed){
      let index=remaining.findIndex(value=>value.catalog_item_id===expected.catalog_item_id&&value.name===expected.name);
      if(index<0&&removed.length===1&&remaining.length===1)index=0;
      if(index<0)actions.push({kind:'row_remove',room:next.name,expected});
      else actions.push({kind:'row_update',room:next.name,expected,value:remaining.splice(index,1)[0]});
    }
    for(const value of remaining)actions.push({kind:'row_add',room:next.name,value});
  }
  for(const room of after.filter(room=>!used.has(room.id))){
    actions.push({kind:'room_add',room:room.name,room_type_id:room.room_type_id});
    for(const value of rows(room))actions.push({kind:'row_add',room:room.name,value});
  }
  return actions;
}
