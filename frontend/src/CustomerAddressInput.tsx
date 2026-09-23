import { useEffect, useId, useRef, useState } from 'react';
import { addressRequest, type AddressSuggestion, type SelectedAddress } from './googlePlaces';
import './CustomerAddressInput.css';

export default function CustomerAddressInput({label, base, linkKey, session, initialValue, disabled, onChange}: {
  label: string; base: string; linkKey: string; session: string; initialValue: string; disabled: boolean;
  onChange: (text: string, place: SelectedAddress | null) => void;
}) {
  const id = useId();
  const [text,setText] = useState(initialValue);
  const [query,setQuery] = useState('');
  const [focused,setFocused] = useState(false);
  const [items,setItems] = useState<AddressSuggestion[]>([]);
  const [active,setActive] = useState(-1);
  const [loading,setLoading] = useState(false);
  const [checking,setChecking] = useState(false);
  const [error,setError] = useState('');
  const [retry,setRetry] = useState(0);
  const [searched,setSearched] = useState(false);
  const [manual,setManual] = useState(false);
  const [city,setCity] = useState('');
  const [state,setState] = useState('');
  const states = 'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split(' ');
  function manualChange(street: string, nextCity: string, nextState: string) {
    const formatted = [street.trim(), [nextCity.trim(),nextState].filter(Boolean).join(', ')].filter(Boolean).join(', ');
    onChange(formatted, nextCity.trim() && nextState ? {place_id:'manual',formatted_address:formatted,
      city:nextCity.trim(),state:nextState,country:'US',proof:''} : null);
  }
  const version = useRef(0);
  const selection = useRef<AbortController>();
  const token = useRef(crypto.randomUUID());
  useEffect(() => () => { version.current++; selection.current?.abort(); }, []);
  useEffect(() => {
    if (manual || !focused || disabled || query.trim().length < 3) { setItems([]); setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true); setError(''); setSearched(false);
    const timer = setTimeout(async () => {
      try {
        const result = await addressRequest<{suggestions: AddressSuggestion[]}>(base,linkKey,session,'address-search',
          {text:query.trim(),session_token:token.current},controller.signal);
        if (!controller.signal.aborted) { setItems(result.suggestions); setActive(-1); setSearched(true); }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }, 350);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [base,linkKey,session,query,focused,disabled,retry,manual]);
  async function choose(item: AddressSuggestion) {
    const current = ++version.current;
    selection.current?.abort();
    const controller = new AbortController(); selection.current = controller;
    setQuery(''); setItems([]); setSearched(false); setError(''); setChecking(true);
    setText(item.text); onChange(item.text,null);
    const sessionToken = token.current;
    token.current = crypto.randomUUID();
    try {
      const place = await addressRequest<SelectedAddress>(base,linkKey,session,'address-resolve',
        {place_id:item.place_id,session_token:sessionToken},controller.signal);
      if (current !== version.current || controller.signal.aborted) return;
      setText(place.formatted_address); onChange(place.formatted_address,place);
    } catch (e) {
      if (current === version.current && !controller.signal.aborted) setError((e as Error).message);
    } finally { if (current === version.current) setChecking(false); }
  }
  const expanded = focused && items.length > 0;
  return <div className="cm-address-input">
    <label htmlFor={id}>{label}</label>
    <input id={id} role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={`${id}-options`}
      aria-activedescendant={expanded && active >= 0 ? `${id}-${active}` : undefined} aria-describedby={`${id}-help`}
      value={text} maxLength={200} autoComplete="off" placeholder={manual ? 'Street address or ZIP (optional)' : 'Street address or city, state'}
      onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)}
      onChange={e=>{version.current++;selection.current?.abort();setChecking(false);setText(e.target.value);setQuery(e.target.value);setItems([]);setError('');setSearched(false);if(manual)manualChange(e.target.value,city,state);else onChange(e.target.value,null);}}
      onKeyDown={e=>{
        if(e.key==='ArrowDown' && items.length){e.preventDefault();setActive(i=>Math.min(i+1,items.length-1));}
        if(e.key==='ArrowUp' && items.length){e.preventDefault();setActive(i=>Math.max(i-1,0));}
        if(e.key==='Escape'){e.preventDefault();setFocused(false);}
        if(e.key==='Enter'){e.preventDefault();if(expanded && active>=0)void choose(items[active]);}
      }} />
    {expanded && <div className="cm-address-results">
      <ul id={`${id}-options`} role="listbox" aria-label={`${label} suggestions`}>
        {items.map((item,i)=><li id={`${id}-${i}`} key={item.place_id} role="option" aria-selected={i===active}
          onMouseDown={e=>e.preventDefault()} onClick={()=>void choose(item)} onMouseEnter={()=>setActive(i)}>{item.text}</li>)}
      </ul>
      <div className="cm-address-attribution" translate="no">Google Maps</div>
    </div>}
    {manual && <div className="cm-address-manual">
      <label htmlFor={`${id}-city`}>City<input id={`${id}-city`} value={city} maxLength={200} onChange={e=>{setCity(e.target.value);manualChange(text,e.target.value,state);}} /></label>
      <label htmlFor={`${id}-state`}>State<select id={`${id}-state`} value={state} onChange={e=>{setState(e.target.value);manualChange(text,city,e.target.value);}}><option value="">Select state</option>{states.map(s=><option key={s}>{s}</option>)}</select></label>
    </div>}
    <small id={`${id}-help`} role="status">{manual ? 'Enter the city and state. This address is entered manually.' : checking ? 'Checking address...' : loading ? 'Searching addresses...' : searched && !items.length && focused ? 'No matches. Try a street address or city and state.' : 'Select a suggestion with at least a city and state.'}</small>
    {!manual && <button type="button" className="slds-button" onClick={()=>{version.current++;selection.current?.abort();setChecking(false);setManual(true);setError('');setItems([]);manualChange(text,city,state);}}>Enter address manually</button>}
    {error && <div role="alert" className="cm-address-error">{error}<button type="button" className="slds-button" disabled={disabled || text.trim().length<3} onClick={()=>{setFocused(true);setQuery(text);setRetry(n=>n+1);}}>Try again</button></div>}
  </div>;
}
