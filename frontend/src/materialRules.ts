export type MaterialRule = {
  protection:'fabric'|'fragile'|'both'; item_type:string; variant:string;
  measure:'none'|'cubic_feet'|'screen_inches'; minimum:number|null; maximum:number|null;
  minimum_inclusive:boolean; maximum_inclusive:boolean;
  unit:'item'|'foot'|'sheet'|'roll'; units_per_item:number;
};
export const emptyRule = ():MaterialRule => ({protection:'fabric',item_type:'any',variant:'',measure:'none',minimum:null,maximum:null,
  minimum_inclusive:true,maximum_inclusive:true,unit:'item',units_per_item:1});
export const defaultBoxCapacity = (index:number):number|null => ({0:2,1:2,2:3,3:5,4:6,9:3,10:6,11:6,19:10,20:15,23:16} as Record<number,number>)[index] ?? null;
export function defaultMaterialRule(index:number):MaterialRule|null {
  const base=emptyRule();
  if(index>=5 && index<=8)return {...base,item_type:'mattress',variant:['twin','full','queen','king'][index-5]};
  if(index===15)return {...base,measure:'cubic_feet',minimum:25,minimum_inclusive:false};
  if(index===16)return {...base,measure:'cubic_feet',maximum:25};
  if(index===19)return {...base,protection:'fragile',item_type:'tv',measure:'screen_inches',maximum:61};
  if(index===20)return {...base,protection:'fragile',item_type:'tv',measure:'screen_inches',minimum:61,minimum_inclusive:false};
  if(index===26)return {...base,item_type:'sofa'};
  if(index===29)return {...base,item_type:'bed_frame'};
  return null;
}
