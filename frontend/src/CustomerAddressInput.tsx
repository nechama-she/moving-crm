import { useEffect, useId, useRef, useState } from 'react';
import { browserSuggestions, type AddressSuggestion, type SelectedAddress } from './googlePlaces';
import './CustomerAddressInput.css';

export default function CustomerAddressInput({label, apiKey, initialValue, disabled, error, onChange}: {
  label: string; apiKey: string; initialValue: string; disabled: boolean;
  error?: string;
  onChange: (text: string, place: SelectedAddress | null) => void;
}) {
  const id = useId();
  const [text,setText] = useState(initialValue);
  const [query,setQuery] = useState('');
  const [focused,setFocused] = useState(false);
  const [items,setItems] = useState<AddressSuggestion[]>([]);
  const [active,setActive] = useState(-1);
  const version = useRef(0);
  useEffect(() => () => { version.current++;  }, []);
  useEffect(() => {
    if (!focused || disabled || query.trim().length < 3) { setItems([]); return; }
    const controller = new AbortController();
    const current = version.current;
    const timer = setTimeout(async () => {
      try {
        const suggestions = await browserSuggestions(apiKey,query.trim(),controller.signal);
        if (!controller.signal.aborted && current === version.current) { setItems(suggestions); setActive(-1); }
      } catch { if (!controller.signal.aborted && current === version.current) setItems([]); }
    }, 350);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [apiKey,query,focused,disabled]);
  function choose(item: AddressSuggestion) {
    version.current++;
    setQuery(''); setItems([]);
    setText(item.text); onChange(item.text,null);
  }
  const expanded = focused && items.length > 0;
  return <div className="cm-address-input">
    <label htmlFor={id}>{label}</label>
    <div className="cm-address-control">
    <input id={id} role="combobox" aria-invalid={!!error} aria-describedby={error ? `${id}-error` : undefined} aria-autocomplete="list" aria-expanded={expanded} aria-controls={`${id}-options`}
      aria-activedescendant={expanded && active >= 0 ? `${id}-${active}` : undefined}
      value={text} maxLength={200} autoComplete="off" placeholder="Street address or city, state"
      onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)}
      onChange={e=>{version.current++;setText(e.target.value);setQuery(e.target.value);setItems([]);onChange(e.target.value,null);}}
      onKeyDown={e=>{
        if(e.key==='ArrowDown' && items.length){e.preventDefault();setActive(i=>Math.min(i+1,items.length-1));}
        if(e.key==='ArrowUp' && items.length){e.preventDefault();setActive(i=>Math.max(i-1,0));}
        if(e.key==='Escape'){e.preventDefault();setFocused(false);}
        if(e.key==='Enter'){e.preventDefault();e.stopPropagation();if(expanded && active>=0)void choose(items[active]);}
      }} />
    {expanded && <div className="cm-address-results">
      <ul id={`${id}-options`} role="listbox" aria-label={`${label} suggestions`}>
        {items.map((item,i)=><li id={`${id}-${i}`} key={item.place_id} role="option" aria-selected={i===active}
          onMouseDown={e=>e.preventDefault()} onClick={()=>void choose(item)} onMouseEnter={()=>setActive(i)}>{item.text}</li>)}
      </ul>
      <div className="cm-address-attribution" translate="no">Google Maps</div>
    </div>}
    </div>
    {error && <small id={`${id}-error`} className="cm-field-error" role="alert">{error}</small>}
  </div>;
}
