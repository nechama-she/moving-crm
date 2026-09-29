import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import "./InventoryCatalogPage.css";

type CatalogMaterial = {plan_id:string; material_id:string; requirement:'required'|'optional'; quantity:number|string};
type MaterialOption = {plan_id:string; plan_name:string; material_id:string; name:string};
export type CatalogItem = { id: string; name: string; description: string; cuft: number; weight: number; active: boolean; packing_materials?:CatalogMaterial[] };

export default function CatalogItemDialog({ item, initialName = "", onClose, onSaved }: {
  item?: CatalogItem; initialName?: string; onClose: () => void; onSaved: (item: CatalogItem) => void;
}) {
  const { token } = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(item?.name || initialName);
  const [description, setDescription] = useState(item?.description || "");
  const [cuft, setCuft] = useState(item ? String(item.cuft) : "");
  const [weight, setWeight] = useState(item ? String(item.weight) : "0");
  const [active, setActive] = useState(item?.active ?? true);
  const [materials,setMaterials] = useState<CatalogMaterial[]>(item?.packing_materials || []);
  const [options,setOptions] = useState<MaterialOption[]>([]);
  const [materialError,setMaterialError] = useState('');
  useEffect(()=>{
    const controller=new AbortController();
    fetch(`${API_BASE}/api/inventory-catalog/material-options`,{headers:authHeaders(token),signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error('Could not load materials.');return response.json();})
      .then(body=>setOptions(body.items))
      .catch(e=>{if(e.name!=='AbortError')setMaterialError(e.message);});
    return ()=>controller.abort();
  },[token]);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const saving = useRef(false);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (saving.current) return;
    saving.current = true; setBusy(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/inventory-catalog${item ? `/${encodeURIComponent(item.id)}` : ""}`, {
        method: item ? "PUT" : "POST", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, cuft, weight, active, packing_materials:materials }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Check the item name, volume, and weight, then try again.");
      onSaved(body);
    } catch (e) { setError((e as Error).message); }
    finally { saving.current = false; setBusy(false); }
  }
  return createPortal(<dialog className="ic-dialog" ref={dialog} aria-labelledby="ic-dialog-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={save}>
      <header className="ic-toolbar"><h2 id="ic-dialog-title">{item ? "Edit catalog item" : "Add catalog item"}</h2><button type="button" className="slds-button slds-button_neutral" onClick={onClose} disabled={busy} aria-label="Close item editor">Close</button></header>
      <p>Catalog items are shared across companies.</p>
      <fieldset disabled={busy}>
        <label>Item name<input autoFocus required maxLength={255} value={name} onChange={e => setName(e.target.value)} /></label>
        <div className="ic-measurements">
          <label>Volume per item (cu ft)<input type="number" required min="0.01" max="10000" step="0.01" value={cuft} onChange={e => setCuft(e.target.value)} /></label>
          <label>Weight per item (lb)<input type="number" required min="0" max="1000000" step="0.01" value={weight} onChange={e => setWeight(e.target.value)} /></label>
        </div>
        <label>Description (optional)<textarea maxLength={2000} value={description} onChange={e => setDescription(e.target.value)} /></label>
        {(['required','optional'] as const).map(requirement=><section className="ic-materials" key={requirement}>
          <div className="ic-toolbar"><h3>{requirement==='required'?'Required materials':'Optional materials'}</h3>
            <button type="button" className="slds-button slds-button_neutral" title="Add material" aria-label={`Add ${requirement} material`} disabled={!options.length}
              onClick={()=>setMaterials([...materials,{plan_id:'',material_id:'',requirement,quantity:1}])}>+</button></div>
          {materials.map((row,index)=>row.requirement===requirement && <div className="ic-material-row" key={index}>
            <label>Material<select required value={JSON.stringify([row.plan_id,row.material_id])} onChange={e=>{
              const [plan_id,material_id]=JSON.parse(e.target.value);
              setMaterials(materials.map((entry,i)=>i===index?{...entry,plan_id,material_id}:entry));
            }}><option value={'["",""]'}>Select material</option>
              {row.material_id && !options.some(option=>option.plan_id===row.plan_id && option.material_id===row.material_id) && <option value={JSON.stringify([row.plan_id,row.material_id])}>Unavailable material (saved)</option>}
              {options.map(option=><option key={JSON.stringify([option.plan_id,option.material_id])} value={JSON.stringify([option.plan_id,option.material_id])}
                disabled={materials.some((entry,i)=>i!==index && entry.plan_id===option.plan_id && entry.material_id===option.material_id)}>{option.plan_name}: {option.name}</option>)}
            </select></label>
            <label>Qty / item<input type="number" required min="0.01" max="10000" step="0.01" value={row.quantity} onChange={e=>setMaterials(materials.map((entry,i)=>i===index?{...entry,quantity:e.target.value}:entry))}/></label>
            <button type="button" className="slds-button slds-button_neutral" title="Remove material" aria-label={`Remove ${requirement} material`} onClick={()=>setMaterials(materials.filter((_,i)=>i!==index))}>&times;</button>
          </div>)}
        </section>)}
        {materialError && <p role="alert" className="ic-error">{materialError}</p>}
        {item && <label className="ic-checkbox"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} /> Available for new selections</label>}
      </fieldset>
      {error && <p role="alert" className="ic-error">{error}</p>}
      <footer className="ic-actions"><button type="button" className="slds-button slds-button_neutral" disabled={busy} onClick={onClose}>Cancel</button><button className="slds-button slds-button_brand" disabled={busy}>{busy ? "Saving..." : item ? "Save item" : "Add item"}</button></footer>
    </form>
  </dialog>, document.body);
}
