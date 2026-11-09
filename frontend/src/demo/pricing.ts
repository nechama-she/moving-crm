// Demo pricing books for the Pricing page. Invented rates only.
import { demoCompanies } from "./fixtures";

const BOOKS = [
  { id: "pb-gorilla-east", company: "c-gorilla", name: "East", regions: "MD, VA, DC" },
  { id: "pb-gorilla-midwest", company: "c-gorilla", name: "Midwest", regions: "IL, IN, OH" },
  { id: "pb-top-east", company: "c-top", name: "East", regions: "NY, NJ, PA" },
  { id: "pb-wilson-se", company: "c-wilson", name: "South East", regions: "NC, SC, GA, FL" },
  { id: "pb-m95", company: "c-m95", name: "MD, VA, DC, DE, PA", regions: "MD, VA, DC, DE, PA" },
];
const DESTINATIONS = ["Florida", "Georgia", "North Carolina", "New York", "Texas", "Illinois"];
const BANDS: [string, number, number | null][] = [["Up to 500 cf", 0, 500], ["501–1,000 cf", 501, 1000], ["1,001–2,000 cf", 1001, 2000], ["Over 2,000 cf", 2001, null]];
const companyName = (id: string) => demoCompanies.find(c => c.id === id)?.name || "Company";

function summary(book: typeof BOOKS[number]) {
  return {
    id: book.id, company_name: companyName(book.company), name: book.name, pickup_regions: `Pickups from ${book.regions}.`,
    pickup_areas: [], fuel_percent: 12, price_valid_days: 7, rate_count: DESTINATIONS.length * BANDS.length,
    rule_count: 3, service_count: 4, updated_at: new Date().toISOString(),
  };
}

export const pricingBooks = () => BOOKS.map(summary);

export function pricingBook(id: string) {
  const book = BOOKS.find(b => b.id === id) || BOOKS[0];
  const seed = BOOKS.indexOf(book) + 1;
  return {
    ...summary(book), active: true, source_file: "", source_sheet: "",
    rules: [
      { id: "r1", category: "General", title: "Price validity", description: "Quotes are valid for 7 days from the estimate date." },
      { id: "r2", category: "General", title: "Fuel", description: "Fuel surcharge applies to the transportation charge." },
      { id: "r3", category: "Delivery", title: "Delivery window", description: "Delivery within 7–21 business days after pickup." },
    ],
    rates: DESTINATIONS.flatMap((destination, d) => BANDS.map(([label, min, max], b) => ({
      id: `${id}-${d}-${b}`, destination, destination_group: "", minimum_price: 1800 + d * 150, minimum_text: "",
      band_label: label, cubic_feet_min: min, cubic_feet_max: max, rate: Number((5.9 + d * 0.35 - b * 0.4 + seed * 0.05).toFixed(2)), rate_text: "",
    }))),
    services: [
      { id: "s1", name: "Shrink wrap per item", rate_text: "$8", comments: "" },
      { id: "s2", name: "Appliance disconnect", rate_text: "$65", comments: "" },
      { id: "s3", name: "Piano handling", rate_text: "$350", comments: "" },
      { id: "s4", name: "TV crate", rate_text: "$145", comments: "" },
    ],
  };
}

export function localPricing() {
  return {
    office_address: "1200 Example Pkwy, Rockville, MD 20850",
    settings: {
      travel_hourly_rate: null, travel_in_minimum: false, fuel_charge: 99, minimum_hours: 3, capacity_per_mover: 95, full_pack_hourly: 45,
      hourly_rates: [99, 139, 179, 229, 279, 329, 379, 429, 479, 529],
      crew_thresholds: [300, 900, 1600, 2400, 3200, 4000, 4800, 5600, 6400],
      truck_thresholds: [1400, 2800, 4200, null, null, null, null, null, null],
    },
    routes: [
      { id: "lr1", pickup: "MD", delivery: "VA(201XX-232XX)" },
      { id: "lr2", pickup: "MD", delivery: "DC" },
      { id: "lr3", pickup: "DC", delivery: "VA(201XX-232XX)" },
      { id: "lr4", pickup: "VA(201XX-232XX)", delivery: "MD" },
    ],
  };
}

export function localQuote(body: { cubic_feet?: number; crew_size?: number | null } | null) {
  const volume = Number(body?.cubic_feet) || 0;
  const crew = Number(body?.crew_size) || (volume > 1600 ? 4 : volume > 900 ? 3 : 2);
  const rate = [99, 139, 179, 229, 279][crew - 1] || 229;
  const hours = Math.max(3, Math.ceil((volume / (crew * 95)) * 2) / 2);
  const total = Math.round(hours * rate + 99);
  return {
    travel_complete: false, travel_hours: 0, travel_hourly_rate: null, recommended_crew: crew, crew_size: crew, trucks: volume > 1400 ? 2 : 1,
    capacity: crew * 95, estimated_hours: hours, base_hours: hours, packing_hours: 0, billable_hours: hours, hourly_rate: rate, full_pack_hourly: 0,
    minimum_applied: hours === 3, total, warning: "",
    charges: [
      { name: "Moving labor", description: `${hours} hours × ${crew} movers`, subtotal: hours * rate, discountAmount: 0, totalCost: hours * rate },
      { name: "Fuel charge", description: "Per move", subtotal: 99, discountAmount: 0, totalCost: 99 },
    ],
  };
}
