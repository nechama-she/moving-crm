import { useEffect, useId, useRef, useState } from "react";
import { loadPlaces, selectedAddress, type AutocompleteElement, type GooglePlace, type SelectedAddress } from "./googlePlaces";
import "./CustomerAddressInput.css";

export default function CustomerAddressInput({ label, apiKey, initialValue, disabled, onChange }: {
  label: string; apiKey: string; initialValue: string; disabled: boolean;
  onChange: (text: string, place: SelectedAddress | null) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const widget = useRef<AutocompleteElement>();
  const change = useRef(onChange); change.current = onChange;
  const initial = useRef(initialValue);
  const disabledRef = useRef(disabled); disabledRef.current = disabled;
  const id = useId();
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [checking, setChecking] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!apiKey) { setError("Address search is not configured. Please contact your moving team to change this address."); return; }
    let active = true, version = 0;
    setError(""); setReady(false);
    const authError = () => { if (active) setError("Address search is unavailable. Please contact your moving team."); };
    window.addEventListener("crm-maps-error", authError);
    loadPlaces(apiKey).then(({ PlaceAutocompleteElement }) => {
      if (!active || !host.current) return;
      const input = new PlaceAutocompleteElement({ requestedRegion: "us", placeholder: "Street address or city, state" });
      widget.current = input;
      input.value = initial.current;
      input.disabled = disabledRef.current;
      input.setAttribute("aria-label", label);
      input.setAttribute("description", "Select a suggestion with at least a city and state.");
      input.addEventListener("input", () => {
        version++; setChecking(false); setError("");
        change.current(input.value, null);
      });
      input.addEventListener("gmp-error", authError);
      input.addEventListener("gmp-select", async event => {
        const current = ++version;
        change.current(input.value, null); setChecking(true); setError("");
        try {
          const place = (event as Event & { placePrediction: { toPlace(): GooglePlace } }).placePrediction.toPlace();
          await place.fetchFields({ fields: ["formattedAddress", "addressComponents"] });
          if (!active || current !== version) return;
          const address = selectedAddress(place);
          if (!address) { setError("Choose an address or city that includes both a city and state."); return; }
          input.value = address.formatted_address;
          initial.current = input.value;
          change.current(input.value, address);
        } catch {
          if (active && current === version) setError("We could not confirm this address. Please select a suggestion again.");
        } finally {
          if (active && current === version) setChecking(false);
        }
      });
      // Selecting a suggestion with Enter must not submit the whole move form.
      input.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); } });
      host.current.replaceChildren(input); setReady(true);
    }).catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; version++; window.removeEventListener("crm-maps-error", authError); widget.current?.remove(); widget.current = undefined; };
  }, [apiKey, label, retry]);
  useEffect(() => { if (widget.current) widget.current.disabled = disabled; }, [disabled]);
  return <div className="cm-address-input">
    <label id={id}>{label}</label>
    <div ref={host} aria-labelledby={id} />
    {!ready && <input aria-label={label} value={initialValue} readOnly disabled />}
    <small role="status">{checking ? "Checking address..." : !ready && !error ? "Loading address search..." : "Select a suggestion with at least a city and state."}</small>
    {error && <div role="alert" className="cm-address-error">{error}{apiKey && <button type="button" className="slds-button" disabled={disabled} onClick={() => setRetry(value => value + 1)}>Try again</button>}</div>}
  </div>;
}
