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
  const version = useRef(0);
  const selection = useRef<AbortController>();
  const token = useRef(crypto.randomUUID());
  useEffect(() => () => { version.current++; selection.current?.abort(); }, []);
  useEffect(() => {
    if (!focused || disabled || query.trim().length < 3) { setItems([]); setLoading(false); return; }
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
  }, [base,linkKey,session,query,focused,disabled,retry]);
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
      value={text} disabled={disabled} maxLength={200} autoComplete="off" placeholder="Street address or city, state"
      onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)}
      onChange={e=>{version.current++;selection.current?.abort();setChecking(false);setText(e.target.value);setQuery(e.target.value);setItems([]);setError('');setSearched(false);onChange(e.target.value,null);}}
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
    <small id={`${id}-help`} role="status">{checking ? 'Checking address...' : loading ? 'Searching addresses...' : searched && !items.length && focused ? 'No matches. Try a street address or city and state.' : 'Select a suggestion with at least a city and state.'}</small>
    {error && <div role="alert" className="cm-address-error">{error}<button type="button" className="slds-button" disabled={disabled || text.trim().length<3} onClick={()=>{setFocused(true);setQuery(text);setRetry(n=>n+1);}}>Try again</button></div>}
  </div>;
}
