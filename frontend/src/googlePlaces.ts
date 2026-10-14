export type SelectedAddress = { place_id: string; formatted_address: string; city: string; state: string; country: string; proof: string };
export type AddressSuggestion = { place_id: string; text: string };

type Prediction = { place_id: string; description: string };
type PlacesLibrary = {
  AutocompleteService: new () => {getPlacePredictions(request: {input:string;componentRestrictions:{country:string};types:string[]}, callback:(results:Prediction[] | null,status:string)=>void):void};
};
type DirectionsService = {route(request:{origin:string;destination:string;travelMode:string},callback:(result:{routes:{legs:{distance?:{value:number}}[]}[]} | null,status:string)=>void):void};
type GeocodeResult={address_components:{short_name:string;types:string[]}[];geometry:{location:{lat():number;lng():number}}};
type MapsBrowser = Window & {google?:{maps:{places?:PlacesLibrary;DirectionsService?:new()=>DirectionsService;Geocoder?:new()=>{geocode(request:{address:string;region:string},callback:(results:GeocodeResult[]|null,status:string)=>void):void}}}; __crmAddressReady?:()=>void};
export type PricingLocation={address:string;state:string;zip_code:string;latitude:number;longitude:number};
let loading: Promise<PlacesLibrary> | undefined;

function loadPlaces(key: string): Promise<PlacesLibrary> {
  const browser=window as MapsBrowser;
  if(browser.google?.maps.places) return Promise.resolve(browser.google.maps.places);
  if(!key) return Promise.reject(new Error('Address suggestions unavailable'));
  if(loading) return loading;
  loading=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    const timeout=setTimeout(fail,15000);
    function fail(){clearTimeout(timeout);script.remove();loading=undefined;reject(new Error('Address suggestions unavailable'));}
    browser.__crmAddressReady=()=>{
      const places=browser.google?.maps.places;
      if(!places){fail();return;}
      clearTimeout(timeout);resolve(places);
    };
    script.async=true;script.referrerPolicy='strict-origin';
    script.src='https://maps.googleapis.com/maps/api/js?'+new URLSearchParams({key,libraries:'places',loading:'async',callback:'__crmAddressReady'});
    script.onerror=fail;document.head.appendChild(script);
  });
  return loading;
}

export async function browserSuggestions(key:string,input:string,signal:AbortSignal):Promise<AddressSuggestion[]> {
  if(signal.aborted)return [];
  const places=await loadPlaces(key);
  if(signal.aborted)return [];
  return new Promise(resolve=>{
    let timer: ReturnType<typeof setTimeout>;
    const finish=(rows:AddressSuggestion[])=>{clearTimeout(timer);signal.removeEventListener('abort',abort);resolve(rows);};
    const abort=()=>finish([]);
    signal.addEventListener('abort',abort,{once:true});
    timer=setTimeout(()=>finish([]),10000);
    new places.AutocompleteService().getPlacePredictions({input,componentRestrictions:{country:'us'},types:['geocode']},(results,status)=>{
      clearTimeout(timer);
      finish(!signal.aborted && status==='OK' ? (results || []).map(row=>({place_id:row.place_id,text:row.description})) : []);
    });
  });
}

export async function browserDrivingMeters(key:string,origin:string,destination:string):Promise<number> {
  await loadPlaces(key);
  const Service=(window as MapsBrowser).google?.maps.DirectionsService;
  if(!Service) throw new Error('Driving directions are unavailable. Please try again.');
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Driving directions timed out. Please try again.')),20000);
    new Service().route({origin,destination,travelMode:'DRIVING'},(result,status)=>{
      clearTimeout(timer);
      const legs=result?.routes[0]?.legs;
      if(status!=='OK' || !legs?.length || legs.some(leg=>!Number.isSafeInteger(leg.distance?.value) || leg.distance!.value<0)) {
        reject(new Error(status==='REQUEST_DENIED' ? 'Google denied driving directions for this website. The browser Maps key needs Directions API access.' : 'Could not find a driving route. Check the stop address and try again.'));
        return;
      }
      resolve(legs.reduce((total,leg)=>total+leg.distance!.value,0));
    });
  });
}

export async function browserPricingLocation(key:string,address:string):Promise<PricingLocation> {
  await loadPlaces(key);
  const Geocoder=(window as MapsBrowser).google?.maps.Geocoder;
  if(!Geocoder) throw new Error('Location lookup unavailable');
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Location lookup timed out')),15000);
    new Geocoder().geocode({address,region:'US'},(results,status)=>{
      clearTimeout(timer);
      const result=results?.[0];
      const part=(type:string)=>result?.address_components.find(row=>row.types.includes(type))?.short_name || '';
      if(status!=='OK' || results?.length!==1 || !result || part('country')!=='US' || !part('administrative_area_level_1')) {
        reject(new Error('Location could not be resolved'));return;
      }
      resolve({address,state:part('administrative_area_level_1'),zip_code:part('postal_code'),latitude:result.geometry.location.lat(),longitude:result.geometry.location.lng()});
    });
  });
}
