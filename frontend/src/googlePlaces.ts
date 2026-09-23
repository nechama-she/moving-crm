export type SelectedAddress = { place_id: string; formatted_address: string; city: string; state: string; country: string; proof: string };
export type AddressSuggestion = { place_id: string; text: string };

export async function addressRequest<T>(base: string, key: string, session: string, action: 'address-search' | 'address-resolve', body: object, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${base}/${action}`, {method:'POST', signal, cache:'no-store',
    headers:{'Content-Type':'application/json','x-public-link':key,'x-public-session':session}, body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Address search is unavailable. Please try again.');
  return result;
}
