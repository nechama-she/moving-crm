import type { MaterialRule } from './materialRules';
export default function MaterialRuleEditor({rule,editing,onChange}:{rule:MaterialRule;editing:boolean;onChange:(rule:MaterialRule)=>void}) {
  const patch=(value:Partial<MaterialRule>)=>onChange({...rule,...value});
  return <fieldset disabled={!editing} style={{border:0,padding:'12px 0',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))',gap:12}}>
    <label>Protection<select value={rule.protection} onChange={e=>patch({protection:e.target.value as MaterialRule['protection']})}>{['fabric','fragile','both'].map(value=><option key={value}>{value}</option>)}</select></label>
    <label>Item type<input value={rule.item_type} onChange={e=>patch({item_type:e.target.value})}/></label>
    <label>Size / variant<input value={rule.variant} onChange={e=>patch({variant:e.target.value})}/></label>
    <label>Size measurement<select value={rule.measure} onChange={e=>patch({measure:e.target.value as MaterialRule['measure'],minimum:null,maximum:null})}><option value="none">No size limit</option><option value="cubic_feet">Item cubic feet</option><option value="screen_inches">Screen inches</option></select></label>
    {rule.measure!=='none' && <>{(['minimum','maximum'] as const).map(key=><label key={key}>{key==='minimum'?'Minimum':'Maximum'}<input type="number" min="0" step="0.01" value={rule[key]??''} onChange={e=>patch({[key]:e.target.value===''?null:Number(e.target.value)})}/><span><input type="checkbox" style={{width:16,height:16}} checked={rule[`${key}_inclusive`]} onChange={e=>patch({[`${key}_inclusive`]:e.target.checked})}/> Include boundary</span></label>)}</>}
    <label>Quantity unit<select value={rule.unit} onChange={e=>patch({unit:e.target.value as MaterialRule['unit']})}>{['item','foot','sheet','roll'].map(value=><option key={value}>{value}</option>)}</select></label>
    <label>Units per item<input type="number" min="0.01" step="0.01" value={rule.units_per_item} onChange={e=>patch({units_per_item:Number(e.target.value)})}/></label>
  </fieldset>;
}
