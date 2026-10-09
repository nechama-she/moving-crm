export type ServiceSelection = string | Record<string, number>;
type Definition = {options:string[]; default?:string};

export function serviceCounts(service:Definition, value:ServiceSelection|undefined, quantity:number):Record<string,number> {
  if (typeof value === 'string' && value) return {[value]:quantity};
  const fallback = service.default || service.options[0];
  const counts:Record<string,number> = {};
  let remaining = quantity;
  for (const [option, count] of Object.entries(value || {})) {
    if (option === fallback) continue;
    counts[option] = Math.min(Math.max(0, count), remaining);
    remaining -= counts[option];
  }
  counts[fallback] = remaining;
  return counts;
}

export function setServiceCount(service:Definition, counts:Record<string,number>, option:string, count:number, quantity:number) {
  const result = {...counts};
  const target = Math.min(quantity, Math.max(0, Math.floor(count)));
  let change = target - (result[option] || 0);
  const fallback = service.default || service.options[0];
  const others = [fallback, ...Object.keys(counts), ...service.options].filter((value, i, all) => value !== option && all.indexOf(value) === i);
  if (!others.length) return counts;
  if (change > 0) {
    for (const other of others) {
      const moved = Math.min(change, result[other] || 0);
      result[other] = (result[other] || 0) - moved;
      change -= moved;
    }
  } else result[others[0]] = (result[others[0]] || 0) - change;
  result[option] = target;
  return result;
}
