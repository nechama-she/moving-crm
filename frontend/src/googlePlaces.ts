export type GooglePlace = {
  id: string;
  formattedAddress?: string;
  addressComponents?: { types: string[]; longText?: string; shortText?: string }[];
  fetchFields(options: { fields: string[] }): Promise<unknown>;
};
export type SelectedAddress = { place_id: string; formatted_address: string; city: string; state: string; country: string };
export type AutocompleteElement = HTMLElement & { value: string; disabled: boolean };
type PlacesLibrary = { PlaceAutocompleteElement: new (options: { requestedRegion: string; placeholder: string }) => AutocompleteElement };
type MapsWindow = Window & {
  google?: { maps: { importLibrary(name: string): Promise<PlacesLibrary> } };
  __crmMapsReady?: () => void;
  gm_authFailure?: () => void;
};
let loading: Promise<PlacesLibrary> | undefined;

export function loadPlaces(key: string): Promise<PlacesLibrary> {
  const browser = window as MapsWindow;
  if (browser.google?.maps.importLibrary) return browser.google.maps.importLibrary("places");
  if (loading) return loading;
  loading = new Promise<PlacesLibrary>((resolve, reject) => {
    const script = document.createElement("script");
    const timer = setTimeout(() => fail(), 20000);
    function fail() {
      clearTimeout(timer);
      script.remove();
      loading = undefined;
      reject(new Error("Address search is unavailable. Please try again or contact your moving team."));
    }
    browser.__crmMapsReady = () => {
      clearTimeout(timer);
      const maps = browser.google?.maps;
      if (!maps) { fail(); return; }
      maps.importLibrary("places").then(resolve, fail);
    };
    const priorAuthFailure = browser.gm_authFailure;
    browser.gm_authFailure = () => {
      priorAuthFailure?.();
      window.dispatchEvent(new Event("crm-maps-error"));
      fail();
    };
    script.async = true;
    script.referrerPolicy = "strict-origin";
    script.src = `https://maps.googleapis.com/maps/api/js?${new URLSearchParams({ key, loading: "async", callback: "__crmMapsReady", v: "weekly", auth_referrer_policy: "origin" })}`;
    script.onerror = fail;
    document.head.appendChild(script);
  });
  return loading;
}

export function selectedAddress(place: GooglePlace): SelectedAddress | null {
  const components = place.addressComponents || [];
  const component = (type: string, short = false) => {
    const part = components.find(row => row.types.includes(type));
    return (short ? part?.shortText : part?.longText)?.trim() || "";
  };
  const city = component("locality") || component("postal_town") || component("sublocality_level_1");
  const state = component("administrative_area_level_1", true);
  const country = component("country", true);
  if (!place.id || !place.formattedAddress || !city || !state || !country) return null;
  return { place_id: place.id, formatted_address: place.formattedAddress, city, state, country };
}
