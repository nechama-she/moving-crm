import ExtraStopsPricingCard, { isExtraStopsCard } from './ExtraStopsPricingCard';
import ElevatorPricingCard, { isElevatorCard } from './ElevatorPricingCard';
import LongCarryPricingCard, { isLongCarryCard } from './LongCarryPricingCard';
import StairsPricingCard, { isStairsCard } from './StairsPricingCard';
import JobDatePicker from './JobDatePicker';
import StoragePricingCard, { isStorageCard } from './StoragePricingCard';
import DeliveryFeesCard, { isDeliveryFeesCard, isOriginFeesCard } from './DeliveryFeesCard';
import ShuttleCard, { isShuttleCard } from './ShuttleCard';
import PickupAreasCard, { type PickupArea } from './PickupAreasCard';
import BulkyCatalogPicker from './BulkyCatalogPicker';
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import LocalPricing from "./LocalPricing";
import LongDistancePackingCard, { isPackingCard, PACKING_CARD_PREFIX } from "./LongDistancePackingCard";
import LongDistanceMaterialsCard, { materialRows, withMaterials } from './LongDistanceMaterialsCard';
import ItemMaterialsCard from './ItemMaterialsCard';
import ItemSelectorsCard from './ItemSelectorsCard';
import { API_BASE } from "./apiConfig";
import { authHeaders, useAuth } from "./AuthContext";
import { calculateDiscounts, type Discount as CustomDiscount } from './pricingDiscounts';

type PlanSummary = {
  id: string; company_name: string; name: string; pickup_regions: string; pickup_areas?: PickupArea[];
  fuel_percent: number | null; price_valid_days: number; rate_count: number; rule_count: number;
  service_count: number; updated_at: string;
};
type Rule = { id?: string; category: string; title: string; description: string };
type Rate = {
  id?: string; destination: string; destination_group: string;
  minimum_price: number | null; minimum_text: string; band_label: string;
  cubic_feet_min: number | null; cubic_feet_max: number | null;
  rate: number | null; rate_text: string;
};
type RateGroup = {
  key: string;
  rowIds: string[];
  destination: string;
  destinationGroup: string;
  minimumPrice: number | null;
  minimumText: string;
  rates: Rate[];
};
type Service = { id?: string; name: string; rate_text: string; comments: string };
type Plan = PlanSummary & {
  active: boolean; source_file: string; source_sheet: string;
  rules: Rule[]; rates: Rate[]; services: Service[];
};
type CalculatedCharge = {
  id: string; name: string; description: string; calculation_type: string;
  rate: number; default_selected: boolean; automatic: boolean; applies: boolean;
  required?: boolean; subtotal?: number; discount_amount?: number; discount_percent?: number;
  quantity_label: string; free_months?: number; selected: boolean; amount: number;
  breakdown?: { label: string; amount: number }[];
};
type Calculation = {
  match: Rate | null; transport: number | null; minimum: number | null;
  minimum_applied: boolean; base_price: number | null; charges: CalculatedCharge[];
  total: number; warning: string;
};
type CustomCharge = { id: string; title: string; amount: number };
const isDiscountRule = (rule: Rule) => rule.category.startsWith('discount_');
type JobMaterial = { name: string; quantity?: number };
type JobContext = {
  lead: { id: string; full_name: string; volume: number | null; weight: number | null };
  job: { id: string; job_order: number; company_name: string; pickup_zip: string; delivery_zip: string; pickup_state: string; pickup_zip_code: string; delivery_state: string; delivery_zip_code: string; move_date: string; booked_move_date: string; estimated_materials?: JobMaterial[] };
  plans: PlanSummary[];
  elevator?: { locations: { location: 'pickup' | 'delivery'; uses_elevator: boolean | null }[] } | null;
  long_carry?: { locations: { location: 'pickup' | 'delivery'; distance_feet: number | null }[] } | null;
  stairs?: { locations: { location: 'pickup' | 'delivery'; flights: number | null }[] } | null;
  storage?: { available_date: string } | null;
  shuttle?: { answer: boolean | null } | null;
  recommended_plan_id: string;
  destination_by_plan?: Record<string,string>;
  move_type: string;
  serviceability: "supported" | "unknown_pickup" | "unsupported_pickup";
};

const BULKY_ITEM_MARKER = "__bulky_item__";
const BULKY_ITEM_PREFIX = `${BULKY_ITEM_MARKER}:`;

type BulkyItemPrices = { handling: string; packing: string; crating: string };

const isBulkyItem = (service: Service) => service.comments === BULKY_ITEM_MARKER || service.comments.startsWith(BULKY_ITEM_PREFIX);

function bulkyItemPrices(service: Service): BulkyItemPrices {
  if (service.comments.startsWith(BULKY_ITEM_PREFIX)) {
    try {
      const data = JSON.parse(service.comments.slice(BULKY_ITEM_PREFIX.length)) as Partial<BulkyItemPrices>;
      return { handling: data.handling || service.rate_text || "", packing: data.packing || "", crating: data.crating || "" };
    } catch {
      return { handling: service.rate_text || "", packing: "", crating: "" };
    }
  }
  return { handling: service.rate_text || "", packing: "", crating: "" };
}

function bulkyItemComments(prices: BulkyItemPrices) {
  return `${BULKY_ITEM_PREFIX}${JSON.stringify(prices)}`;
}

const money = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString("en-US", { style: "currency", currency: "USD" });

function roundedCubicFeet(value: string | number | null | undefined): string {
  if (value == null || value === "") return "";
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return "";
  return String(Math.ceil(parsed));
}

function cubicFeetValue(value: string | number | null | undefined): number {
  return Number(roundedCubicFeet(value) || 0);
}

function formatApiError(data: unknown, fallback = "An error occurred"): string {
  if (!data) return fallback;
  if (typeof data === "string") return data;
  const detail = (data as { detail?: unknown; message?: unknown; error?: unknown })?.detail
    ?? (data as { detail?: unknown; message?: unknown; error?: unknown })?.message
    ?? (data as { detail?: unknown; message?: unknown; error?: unknown })?.error;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d: unknown) => typeof d === "string" ? d : (d as { msg?: string })?.msg || JSON.stringify(d)).join("; ") || fallback;
  }
  if (typeof detail === "object" && detail !== null) {
    return (detail as { msg?: string }).msg || JSON.stringify(detail);
  }
  return fallback;
}

function destinationFromAddress(address: string | null | undefined, options: string[] = [], resolvedState = "", resolvedZip = ""): string {
  const safeAddress = String(address || "");
  const state = (resolvedState || safeAddress.toUpperCase().match(/(?:,\s*|\b)([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?|\b)/)?.[1] || "").toUpperCase();
  if (!state) return "";
  const zip = resolvedZip || safeAddress.match(/\b(\d{5})(?:-\d{4})?\b/)?.[1] || "";
  const zipDigits = zip.replace(/\D/g, "");
  const stateOptions = (options || []).filter((option) => option && (option.toUpperCase() === state || option.toUpperCase().startsWith(`${state} `) || option.toUpperCase().startsWith(`${state}(`)));
  if (zipDigits) {
    const ranged = stateOptions.find((option) => {
      const numbers = option.match(/\d+/g) || [];
      if (numbers.length >= 2 && /[-–—]|\bto\b/i.test(option)) {
        const start = numbers[0] || "";
        const end = numbers[1] || "";
        const width = Math.min(start.length, end.length);
        const value = Number(zipDigits.slice(0, width));
        return Number(start.slice(0, width)) <= value && value <= Number(end.slice(0, width));
      }
      return numbers.some((number) => zipDigits.startsWith(number) || number.startsWith(zipDigits));
    });
    if (ranged) return ranged;
  }
  return stateOptions.find((option) => option.toUpperCase() === state)
    || stateOptions.find((option) => !/\d/.test(option))
    || "";
}

export default function PricingPage() {
  const { token, user } = useAuth();
  const [bulkyCatalogIndex, setBulkyCatalogIndex] = useState<number | null>(null);
  const [searchParams] = useSearchParams();
  const leadId = searchParams.get("lead_id") || "";
  const jobId = searchParams.get("job_id") || "";
  const [pricingMode, setPricingMode] = useState<"local" | "long-distance">("local");
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [draft, setDraft] = useState<Plan | null>(null);
  const [editing, setEditing] = useState(false);
  const [sectionEditing, setSectionEditing] = useState<string[]>([]);
  const [discountOpen, setDiscountOpen] = useState(false);
  const [discountDraft, setDiscountDraft] = useState<Rule[] | null>(null);
  const [savingDiscounts, setSavingDiscounts] = useState(false);
  const [discountError, setDiscountError] = useState('');
  useEffect(() => { setDiscountOpen(false); setDiscountDraft(null); setDiscountError(''); }, [plan?.id]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingPrice, setSavingPrice] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const calculationId = useRef(0);
  const priceSaveRunning = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [destination, setDestination] = useState("");
  const [cubicFeet, setCubicFeet] = useState("");
  const [quote, setQuote] = useState<Calculation | null>(null);
  const [jobContext, setJobContext] = useState<JobContext | null>(null);
  const [selectedCharges, setSelectedCharges] = useState<Record<string, boolean>>({});
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [manualAmounts, setManualAmounts] = useState<Record<string, number>>({});
  const [customCharges, setCustomCharges] = useState<CustomCharge[]>([]);
  const [customDiscounts, setCustomDiscounts] = useState<CustomDiscount[]>([]);
  const [storagePickupDate, setStoragePickupDate] = useState('');
  const [elevatorAnswers, setElevatorAnswers] = useState<Partial<Record<'pickup' | 'delivery', string>>>({});
  const [carryFeet, setCarryFeet] = useState<Partial<Record<'pickup' | 'delivery', string>>>({});
  const [stairsFlights, setStairsFlights] = useState<Partial<Record<'pickup' | 'delivery', string>>>({});
  const [availableDate, setAvailableDate] = useState('');
  const [pickupAddress, setPickupAddress] = useState('');
  const [deliveryAddress, setDeliveryAddress] = useState('');
  const [openSections, setOpenSections] = useState({ materials: false, extraStops: false, elevator: false, longCarry: false, stairs: false, storage: false, originFees: false, deliveryFees: false, shuttle: false, pickup: false, rates: false, packing: false, bulkyItems: false, services: false });
  const [pendingRateGroups, setPendingRateGroups] = useState<string[][]>([]);

  useEffect(() => {
    if (leadId && jobId) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void fetch(`${API_BASE}/api/pricing`, { headers: authHeaders(token), signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(formatApiError(body, "Failed to load pricing"));
        }
        return response.json();
      })
      .then((rows: PlanSummary[]) => {
        if (controller.signal.aborted) return;
        setPlans(rows);
        setSelectedId((current) => rows.some((row) => row.id === current) ? current : (rows[0]?.id || ""));
        if (!rows.length) {
          setPlan(null);
          setDraft(null);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Failed to load pricing");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [token, leadId, jobId]);

  useEffect(() => {
    if (!leadId || !jobId) return;
    const controller = new AbortController();
    void fetch(`${API_BASE}/api/pricing/context?lead_id=${encodeURIComponent(leadId)}&job_id=${encodeURIComponent(jobId)}`, { headers: authHeaders(token), signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(formatApiError(body, "Failed to load job pricing"));
        }
        return response.json();
      })
      .then((context: JobContext) => {
        if (controller.signal.aborted) return;
        setJobContext(context);
        setPlans(context.plans);
        setPricingMode(context.move_type === "Local" ? "local" : "long-distance");
        setSelectedId(context.recommended_plan_id || context.plans[0]?.id || "");
        if (!context.recommended_plan_id) {
          setPlan(null);
          setDraft(null);
        }
        setCubicFeet(roundedCubicFeet(context.lead.volume));
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Failed to load job pricing");
      });
    return () => controller.abort();
  }, [token, leadId, jobId]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setEditing(false);
    setAvailableDate('');
    setStoragePickupDate('');
    setElevatorAnswers({});
    setCarryFeet({});
    setStairsFlights({});
    setOpenSections({ materials: false, extraStops: false, elevator: false, longCarry: false, stairs: false, storage: false, originFees: false, deliveryFees: false, shuttle: false, pickup: false, rates: false, packing: false, bulkyItems: false, services: false });
    calculationId.current++;
    setCalculating(false);
    setQuote(null);
    void fetch(`${API_BASE}/api/pricing/${selectedId}`, { headers: authHeaders(token), signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(formatApiError(body, "Failed to load pricing plan"));
        }
        return response.json();
      })
      .then((row: Plan) => {
        if (controller.signal.aborted) return;
        setPlan(row);
        setDraft(structuredClone(row));
        setPendingRateGroups([]);
        const options = Array.from(new Set((row.rates || []).map((rate) => rate.destination).filter(Boolean)));
        const inferredDestination = jobContext?.destination_by_plan?.[row.id] ?? destinationFromAddress(
          jobContext?.job?.delivery_zip || "",
          options,
          jobContext?.job?.delivery_state || "",
          jobContext?.job?.delivery_zip_code || "",
        );
        setDestination(inferredDestination || (jobContext ? "" : options[0] || ""));
        setSelectedCharges({});
        setQuantities({});
        setManualAmounts({});
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Failed to load pricing plan");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedId, token]);

  const hasPendingRateGroups = pendingRateGroups.length > 0;
  const active = editing || sectionEditing.length > 0 || hasPendingRateGroups ? draft : plan;
  const editingSection = (section: string) => sectionEditing.includes(section);
  useEffect(() => { setSectionEditing([]); }, [plan?.id]);
  const destinations = useMemo(
    () => Array.from(new Set((active?.rates || []).map((row) => row.destination).filter(Boolean))),
    [active],
  );
  const bands = useMemo(
    () => Array.from(new Set((active?.rates || []).map((row) => row.band_label).filter(Boolean))),
    [active],
  );
  useEffect(() => {
    if (!plan || !jobContext) return;
    const options = Array.from(new Set((plan.rates || []).map((rate) => rate.destination).filter(Boolean)));
    const inferred = jobContext.destination_by_plan?.[plan.id] ?? destinationFromAddress(
      jobContext.job?.delivery_zip || "",
      options,
      jobContext.job?.delivery_state || "",
      jobContext.job?.delivery_zip_code || "",
    );
    setDestination(inferred);
  }, [jobContext, plan]);
  const rateRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    const rows = active?.rates || [];
    const originalById = new Map((plan?.rates || []).map(row => [row.id, row]));
    const originalRow = (row: Rate) => editing || hasPendingRateGroups ? originalById.get(row.id) || row : row;
    const pendingIdSets = pendingRateGroups.map((ids) => new Set(ids));
    const usedIds = new Set<string>();
    const groups: RateGroup[] = [];

    pendingIdSets.forEach((idSet) => {
      const groupRates = rows.filter((row) => row.id && idSet.has(row.id));
      if (!groupRates.length) return;
      groupRates.forEach((row) => { if (row.id) usedIds.add(row.id); });
      const seed = groupRates[0];
      groups.push({
        key: seed.id || groupRates.map((row) => row.band_label).join("|"),
        rowIds: groupRates.map((row) => row.id).filter((id): id is string => Boolean(id)),
        destination: seed.destination || "",
        destinationGroup: seed.destination_group || "",
        minimumPrice: seed.minimum_price ?? null,
        minimumText: seed.minimum_text || "",
        rates: groupRates,
      });
    });

    const grouped = new Map<string, Rate[]>();
    rows.forEach((row) => {
      if (row.id && usedIds.has(row.id)) return;
      // Editing a label must not regroup/remount the inputs, including when it
      // temporarily matches another destination or becomes blank.
      const key = originalRow(row).destination.trim() || `blank:${row.id || row.band_label}`;
      const existing = grouped.get(key);
      if (existing) existing.push(row);
      else grouped.set(key, [row]);
    });

    grouped.forEach((groupRates, key) => {
      const seed = groupRates[0];
      groups.push({
        key: seed.id || key,
        rowIds: groupRates.map((row) => row.id).filter((id): id is string => Boolean(id)),
        destination: seed.destination || "",
        destinationGroup: seed.destination_group || "",
        minimumPrice: seed.minimum_price ?? null,
        minimumText: seed.minimum_text || "",
        rates: groupRates,
      });
    });

    return groups.sort((a, b) => {
      const pendingA = pendingRateGroups.findIndex(ids => ids.includes(a.rowIds[0]));
      const pendingB = pendingRateGroups.findIndex(ids => ids.includes(b.rowIds[0]));
      if (pendingA >= 0 || pendingB >= 0) return pendingA < 0 ? -1 : pendingB < 0 ? 1 : pendingA - pendingB;
      const referenceA = originalRow(a.rates[0]);
      const referenceB = originalRow(b.rates[0]);
      const areaA = referenceA.destination_group.trim();
      const areaB = referenceB.destination_group.trim();
      // Keep destinations without an area after the named areas.
      if (!areaA !== !areaB) return areaA ? -1 : 1;
      return areaA.localeCompare(areaB, 'en', { sensitivity: 'base', numeric: true })
        || referenceA.destination.trim().localeCompare(referenceB.destination.trim(), 'en', { sensitivity: 'base', numeric: true });
    }).filter((group) => {
      if (!query) return true;
      const reference = originalRow(group.rates[0]);
      return reference.destination.toLowerCase().includes(query) || reference.destination_group.toLowerCase().includes(query);
    });
  }, [active, plan, editing, hasPendingRateGroups, pendingRateGroups, search]);
  const pendingRateGroupKeys = useMemo(
    () => new Set(pendingRateGroups.map((ids) => ids.join("|"))),
    [pendingRateGroups],
  );
  const catalogRules = useMemo(() => {
    if (!active || !active.rules) return [];
    const serviceNames = ((editing ? plan : active)?.services || []).map((service) => (service.name || "").toLowerCase());
    return (active.rules || []).filter((rule) => {
      if (isDiscountRule(rule)) return false;
      const reference = sectionEditing.includes('services') ? plan?.rules.find(original => !!rule.id && original.id === rule.id) : rule;
      // Keep an edited rule visible until Save, even if its text changes category.
      if (!reference) return true;
      const text = (reference.description || "").toLowerCase();
      if (text.includes("destination & origin") && serviceNames.some((name) => name.includes("destination & origin"))) return false;
      if (text.includes("company & fuel") && !text.includes("$")) return false;
      if ((text.includes("pick up from") || text.includes("rates period") || text.includes("to area")) && !/(add|take off|reduce|ask|fee|not included)/i.test(text)) return false;
      if (/^(rates period|exceptions?)$/i.test((reference.description || "").trim())) return false;
      return true;
    });
  }, [active, plan, editing, sectionEditing]);
  const originalService = (service: Service) => editing
    ? plan?.services.find(original => !!service.id && original.id === service.id) || service : service;
  const bulkyItems = (active?.services || []).filter(service => isBulkyItem(originalService(service)));
  const pricingServices = (active?.services || []).filter(service => !isBulkyItem(originalService(service)) && !isPackingCard(originalService(service)) && !isShuttleCard(originalService(service)) && !isOriginFeesCard(originalService(service)) && !isDeliveryFeesCard(originalService(service)) && !isStorageCard(originalService(service)) && !isExtraStopsCard(originalService(service)) && !(active?.services.some(isExtraStopsCard) && /\b(extra|additional)\b.*\bstops?\b/i.test(service.name)) && !isElevatorCard(originalService(service)) && !(active?.services.some(isElevatorCard) && /\belevators?\b/i.test(service.name)) && !isLongCarryCard(originalService(service)) && !(active?.services.some(isLongCarryCard) && /\blong[ -]+carry\b/i.test(service.name)) && !isStairsCard(originalService(service)) && !(active?.services.some(isStairsCard) && /\bstairs?\b|\bstaircases?\b/i.test(service.name)) && !(active?.services.some(isStorageCard) && /^\s*(?:long\s+term\s+)?storage\b/i.test(service.name)));
  const customChargeTotal = useMemo(
    () => customCharges.reduce((sum, charge) => sum + Math.max(0, Number(charge.amount) || 0), 0),
    [customCharges],
  );
  const discountBase = (quote?.total || 0) + customChargeTotal;
  const discountTargets = useMemo(() => {
    const targets: Record<string, number> = { transportation: Math.max(0, quote?.base_price || 0) };
    quote?.charges.filter((charge) => charge.selected).forEach((charge) => { targets[`charge:${charge.id}`] = Math.max(0, charge.amount); });
    customCharges.forEach((charge) => { targets[`custom:${charge.id}`] = Math.max(0, Number(charge.amount) || 0); });
    return targets;
  }, [quote, customCharges]);
  const calculatedDiscounts = useMemo(
    () => calculateDiscounts(customDiscounts, discountTargets, cubicFeetValue(cubicFeet)),
    [customDiscounts, discountTargets, cubicFeet],
  );
  const discountTotal = calculatedDiscounts.reduce((sum, discount) => sum + discount.amount, 0);
  const detailedTotal = Math.max(0, discountBase - discountTotal);

  function startServiceEdit(section: 'materials' | 'extraStops' | 'elevator' | 'longCarry' | 'stairs' | 'storage' | 'originFees' | 'deliveryFees' | 'shuttle' | 'pickup' | 'rates' | 'packing' | 'bulkyItems' | 'services') {
    if (user?.role !== 'admin' || saving) return;
    setOpenSections(current => ({ ...current, [section]: true }));
    setSectionEditing(current => [...new Set([...current, section])]);
  }
  function serviceEditActions(section: 'materials' | 'extraStops' | 'elevator' | 'longCarry' | 'stairs' | 'storage' | 'originFees' | 'deliveryFees' | 'shuttle' | 'pickup' | 'rates' | 'packing' | 'bulkyItems' | 'services') {
    if (user?.role !== 'admin') return null;
    return editingSection(section) ? <>
      <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={saving} onClick={() => cancelSection(section)}>Cancel changes</button>
      <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={saving} onClick={() => void saveSection(section)}>{saving ? 'Saving...' : 'Save changes'}</button>
    </> : <button type="button" className="slds-button pricing-section-action" aria-label={section === 'extraStops' ? 'Edit additional stop pricing' : section === 'elevator' ? 'Edit elevator pricing' : section === 'longCarry' ? 'Edit long carry pricing' : section === 'stairs' ? 'Edit stairs pricing' : section === 'storage' ? 'Edit storage pricing' : section === 'originFees' ? 'Edit origin fees' : section === 'deliveryFees' ? 'Edit destination fees' : section === 'shuttle' ? 'Edit shuttle' : section === 'pickup' ? 'Edit pickup areas' : section === 'rates' ? 'Edit transportation rates' : section === 'packing' ? 'Edit packing rates' : section === 'services' ? 'Edit additional services and adjustments' : 'Edit bulky item rates'} title="Edit" onClick={() => startServiceEdit(section)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16 3 5 5L8 21H3v-5L16 3Z" /><path d="m13 6 5 5" /></svg></button>;
  }

  function patchDraft(patch: Partial<Plan>) {
    setDraft((current) => current ? { ...current, ...patch } : current);
  }
  const serviceSection: Record<string, (service: Service) => boolean> = {
    extraStops: isExtraStopsCard, elevator: isElevatorCard, longCarry: isLongCarryCard,
    stairs: isStairsCard, storage: isStorageCard, originFees: isOriginFeesCard,
    deliveryFees: isDeliveryFeesCard, shuttle: isShuttleCard, packing: isPackingCard,
    materials: isPackingCard, bulkyItems: isBulkyItem,
    services: service => ![isExtraStopsCard, isElevatorCard, isLongCarryCard, isStairsCard, isStorageCard, isOriginFeesCard, isDeliveryFeesCard, isShuttleCard, isPackingCard, isBulkyItem].some(matches => matches(service)),
  };
  function mergeSection(current: Plan, saved: Plan, section: string): Plan {
    if (section === 'services') return {...current, services: [...current.services.filter(row => !serviceSection.services(row)), ...structuredClone(saved.services.filter(serviceSection.services))], rules: [...current.rules.filter(isDiscountRule), ...structuredClone(saved.rules.filter(row => !isDiscountRule(row)))]};
    if (section === 'rates') return {...current, rates: structuredClone(saved.rates)};
    if (section === 'pickup') return {...current, pickup_areas: structuredClone(saved.pickup_areas), pickup_regions: saved.pickup_regions};
    const matches = serviceSection[section];
    let rows = structuredClone(saved.services.filter(matches));
    if (section === 'packing' || section === 'materials') {
      const old = current.services.find(isPackingCard);
      const oldConfig = old ? JSON.parse(old.comments.slice(PACKING_CARD_PREFIX.length)) : {};
      const incoming = rows[0] ? JSON.parse(rows[0].comments.slice(PACKING_CARD_PREFIX.length)) : {};
      const merged = {...oldConfig};
      for (const key of section === 'materials' ? ['materials'] : ['full', 'partial', 'unpacking', 'items']) {
        if (key in incoming) merged[key] = incoming[key]; else delete merged[key];
      }
      rows = rows.length || old ? [{...(rows[0] || old!), comments: PACKING_CARD_PREFIX + JSON.stringify(merged)}] : [];
    }
    return {...current, services: [...current.services.filter(service => !matches(service)), ...rows]};
  }
  function cancelSection(section: string) {
    if (plan) setDraft(current => current ? mergeSection(current, plan, section) : current);
    setSectionEditing(current => current.filter(name => name !== section));
    if (section === 'rates') setPendingRateGroups([]);
    setError('');
  }
  async function saveSection(section: string) {
    if (!draft) return;
    setSaving(true); setError(''); setNotice('');
    const body = section === 'rates' ? {rates: draft.rates.map(row => ({...row, id: pendingRateGroups.some(ids => row.id && ids.includes(row.id)) ? undefined : row.id}))}
      : section === 'pickup' ? {pickup_areas: draft.pickup_areas || []}
      : section === 'services' ? {services: draft.services.filter(serviceSection.services), rules: draft.rules.filter(row => !isDiscountRule(row))}
      : {services: (section === 'materials' ? withMaterials(draft.services) : draft.services).filter(serviceSection[section]).map(row => {
        if (section !== 'materials' && section !== 'packing') return row;
        const config = JSON.parse(row.comments.slice(PACKING_CARD_PREFIX.length));
        const keys = section === 'materials' ? ['materials'] : ['full', 'partial', 'unpacking', 'items'];
        return {...row, comments: PACKING_CARD_PREFIX + JSON.stringify(Object.fromEntries(keys.filter(key => key in config).map(key => [key, config[key]])))};
      })};
    try {
      const response = await fetch(`${API_BASE}/api/pricing/${draft.id}/sections/${section}`, {
        method: 'PUT', headers: {...authHeaders(token), 'Content-Type': 'application/json'}, body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(formatApiError(data, 'Could not save section'));
      setPlan(current => current ? mergeSection(current, data, section) : current);
      setDraft(current => current ? mergeSection(current, data, section) : current);
      setSectionEditing(current => current.filter(name => name !== section));
      if (section === 'rates') setPendingRateGroups([]);
      setNotice('Section saved.');
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not save section'); }
    finally { setSaving(false); }
  }
  function addLineDiscount(targetId: string) {
    setCustomDiscounts((rows) => [...rows.filter(row => row.targetId !== targetId), {
      id: crypto.randomUUID(), targetId, title: "", type: "amount", value: 0,
    }]);
  }
  function lineDiscounts(targetId: string) {
    return calculatedDiscounts.filter((discount) => discount.targetId === targetId);
  }
  function patchRule(index: number, patch: Partial<Rule>) {
    if (!draft) return;
    patchDraft({ rules: draft.rules.map((row, idx) => idx === index ? { ...row, ...patch } : row) });
  }
  function patchService(index: number, patch: Partial<Service>) {
    if (!draft) return;
    patchDraft({ services: draft.services.map((row, idx) => idx === index ? { ...row, ...patch } : row) });
  }
  function addBulkyItem() {
    patchDraft({ services: [...(draft?.services || []), { name: "", rate_text: "", comments: bulkyItemComments({ handling: "", packing: "", crating: "" }) }] });
  }
  function patchBulkyItemPrice(index: number, key: keyof BulkyItemPrices, value: string) {
    const service = active?.services[index];
    if (!service) return;
    const prices = { ...bulkyItemPrices(service), [key]: value };
    patchService(index, { rate_text: prices.handling, comments: bulkyItemComments(prices) });
  }
  function removeService(index: number) {
    patchDraft({ services: (draft?.services || []).filter((_, idx) => idx !== index) });
  }
  function patchRate(id: string | undefined, patch: Partial<Rate>) {
    if (!draft) return;
    patchDraft({ rates: draft.rates.map((row) => row.id === id ? { ...row, ...patch } : row) });
  }
  function patchRateGroup(rowIds: string[], patch: Partial<Rate>) {
    if (!rowIds.length) return;
    setDraft((current) => current ? {
      ...current,
      rates: (current.rates || []).map((row) => row.id && rowIds.includes(row.id) ? { ...row, ...patch } : row),
    } : current);
  }
  function addDestination() {
    setOpenSections(current => ({ ...current, rates: true }));
    if (!draft && plan) {
      setDraft(structuredClone(plan));
    }
    const templates = bands.length
      ? bands.map((band) => active?.rates.find((row) => row.band_label === band))
      : [undefined];
    const rows = templates.map((template, index) => ({
      id: crypto.randomUUID(),
      destination: "",
      destination_group: "",
      minimum_price: null,
      minimum_text: "",
      band_label: bands[index] || "",
      cubic_feet_min: template?.cubic_feet_min ?? null,
      cubic_feet_max: template?.cubic_feet_max ?? null,
      rate: null,
      rate_text: "",
    }));
    setDraft((current) => current ? { ...current, rates: [...(current.rates || []), ...rows] } : current);
    setPendingRateGroups((groups) => [...groups, rows.map((row) => row.id)]);
  }
  function removeRateGroup(rowIds: string[]) {
    if (!rowIds.length) return;
    const rowIdSet = new Set(rowIds);
    setDraft((current) => current ? { ...current, rates: (current.rates || []).filter((row) => !row.id || !rowIdSet.has(row.id)) } : current);
    setPendingRateGroups((groups) => groups.filter((ids) => ids.some((id) => !rowIdSet.has(id))));
  }


  async function savePrice() {
    if (!jobContext || !quote || calculating || priceSaveRunning.current || detailedTotal <= 0) return;
    const cents = (amount: number) => Math.round(amount * 100);
    const lines = [
      { id: "transportation", name: "Transportation charge", description: `${cubicFeetValue(cubicFeet)} cf ? ${quote.match?.band_label || "Transportation"}`, amount: quote.base_price || 0 },
      ...quote.charges.filter(charge => charge.selected).map(charge => ({ id: `charge:${charge.id}`, name: charge.name, description: charge.description, amount: charge.amount, subtotal: charge.subtotal, defaultDiscount: charge.discount_amount, pricingKey: (charge.id.startsWith('stairs:') || charge.id.startsWith('long_carry:') || charge.id.startsWith('elevator:') || charge.id.startsWith('extra-stop:')) ? charge.id : undefined })),
      ...customCharges.map(charge => ({ id: `custom:${charge.id}`, name: charge.title.trim() || "Custom charge", description: "Custom charge", amount: Math.max(0, Number(charge.amount) || 0) })),
    ];
    const estimatedCharges = lines.map(line => {
      const discounts = lineDiscounts(line.id);
      const subtotal = cents('subtotal' in line ? line.subtotal ?? line.amount : line.amount);
      const defaultDiscount = 'defaultDiscount' in line ? line.defaultDiscount || 0 : 0;
      const discount = cents(defaultDiscount + discounts.reduce((sum, item) => sum + item.amount, 0));
      return { pricingKey: 'pricingKey' in line ? line.pricingKey : undefined, name: line.name, description: [line.description, ...discounts.filter(item => item.amount > 0).map(item => item.title.trim() || "Discount")].join(" ? "), subtotal: subtotal / 100, discountAmount: discount / 100, totalCost: (subtotal - discount) / 100 };
    }).filter(line => line.totalCost !== 0 || line.discountAmount > 0 || line.description.startsWith('Calculation pending: ')).map((line, sortOrder) => ({ ...line, sortOrder }));
    const price = estimatedCharges.reduce((sum, line) => sum + cents(line.totalCost), 0) / 100;
    if (!Number.isFinite(price) || price <= 0) { setError("Calculate a price greater than zero before saving."); return; }
    priceSaveRunning.current = true;
    setSavingPrice(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${API_BASE}/api/leads/${encodeURIComponent(jobContext.lead.id)}/jobs/${encodeURIComponent(jobContext.job.id)}/price`, {
        method: "PUT", headers: { ...authHeaders(token), "Content-Type": "application/json" },
        body: JSON.stringify({ price, estimatedCharges }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(formatApiError(body, "Could not save price"));
      }
      setNotice(`Price saved to Job ${jobContext.job.job_order}: ${money(price)}.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save price"); }
    finally { priceSaveRunning.current = false; setSavingPrice(false); }
  }

  async function saveDiscounts() {
    if (!plan || !discountDraft) return;
    setSavingDiscounts(true); setDiscountError('');
    try {
      const response = await fetch(`${API_BASE}/api/pricing/${plan.id}/discounts`, {
        method: 'PUT', headers: {...authHeaders(token), 'Content-Type': 'application/json'},
        body: JSON.stringify(discountDraft),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(formatApiError(body, 'Could not save discounts'));
      const merge = (current: Plan | null) => current ? {...current, rules: [...current.rules.filter(rule => !isDiscountRule(rule)), ...body]} : current;
      setPlan(merge); setDraft(merge); setDiscountDraft(null);
    } catch (error) { setDiscountError(error instanceof Error ? error.message : 'Could not save discounts'); }
    finally { setSavingDiscounts(false); }
  }
  function patchDiscount(index: number, patch: Partial<Rule>) {
    setDiscountDraft(rows => rows?.map((row, i) => i === index ? {...row, ...patch} : row) || null);
  }

  async function save() {
    if (!draft) return;
    setSaving(true); setError('');
    try {
      const response = await fetch(`${API_BASE}/api/pricing/${draft.id}/sections/details`, {
        method: 'PUT', headers: {...authHeaders(token), 'Content-Type': 'application/json'},
        body: JSON.stringify({name: draft.name, fuel_percent: draft.fuel_percent, price_valid_days: draft.price_valid_days ?? 7}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(formatApiError(result, 'Could not save price sheet details'));
      const merge = (current: Plan | null) => current ? {...current, name: result.name, fuel_percent: result.fuel_percent, price_valid_days: result.price_valid_days} : current;
      setPlan(merge); setDraft(merge); setEditing(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save details'); }
    finally { setSaving(false); }
  }

  function elevatorValue(place: 'pickup' | 'delivery') {
    const answer = elevatorAnswers[place];
    return answer === undefined ? jobContext?.elevator?.locations.find(r => r.location === place)?.uses_elevator ?? null : answer === '' ? null : answer === 'yes';
  }
  function stairCount(place: 'pickup' | 'delivery') {
    const value = stairsFlights[place];
    return value === undefined ? jobContext?.stairs?.locations.find(row => row.location === place)?.flights ?? null : value === '' ? null : Number(value);
  }

  async function calculate(overrides?: { selected?: Record<string, boolean>; quantities?: Record<string, number>; manual?: Record<string, number> }) {
    if (!active || !destination) return;
    const requestId = ++calculationId.current;
    setCalculating(true); setError(""); setNotice("");
    try {
    const response = await fetch(`${API_BASE}/api/pricing/${active.id}/calculate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify({
        source_job_id: jobContext?.job.id,
        destination,
        pickup_address: jobContext?.job.pickup_zip || pickupAddress,
        delivery_address: jobContext?.job.delivery_zip || deliveryAddress,
        shuttle_access: jobContext?.shuttle?.answer ?? null,
        pickup_elevator: elevatorValue('pickup'),
        delivery_elevator: elevatorValue('delivery'),
        pickup_carry_feet: carryFeet.pickup === undefined ? jobContext?.long_carry?.locations.find(r => r.location === 'pickup')?.distance_feet ?? null : carryFeet.pickup === '' ? null : Number(carryFeet.pickup),
        delivery_carry_feet: carryFeet.delivery === undefined ? jobContext?.long_carry?.locations.find(r => r.location === 'delivery')?.distance_feet ?? null : carryFeet.delivery === '' ? null : Number(carryFeet.delivery),
        pickup_flights: stairCount('pickup'),
        delivery_flights: stairCount('delivery'),
        available_date: availableDate || jobContext?.storage?.available_date || '',
        cubic_feet: cubicFeetValue(cubicFeet),
        move_date: jobContext?.job.move_date || storagePickupDate,
        bulky_items: jobContext?.job.estimated_materials?.flatMap((item) => Array.from({ length: Math.max(1, Math.floor(Number(item.quantity) || 1)) }, () => item.name)).filter(Boolean) || [],
        selected_charges: overrides?.selected || selectedCharges,
        quantities: overrides?.quantities || quantities,
        manual_amounts: overrides?.manual || manualAmounts,
      }),
    });
    if (requestId !== calculationId.current) return;
    if (!response.ok) {
      setQuote(null);
      const body = await response.json().catch(() => ({}));
      setError(formatApiError(body, "Could not calculate pricing"));
      return;
    }
    const result: Calculation = await response.json();
    if (requestId !== calculationId.current) return;
    setQuote(result);
    setSelectedCharges(Object.fromEntries(result.charges.map((charge) => [charge.id, charge.selected])));
    } catch (reason) {
      if (requestId === calculationId.current) { setQuote(null); setError(reason instanceof Error ? reason.message : "Could not calculate pricing"); }
    } finally { if (requestId === calculationId.current) setCalculating(false); }
  }

  useEffect(() => {
    if (!plan || !destination || editing || pricingMode !== "long-distance" || cubicFeetValue(cubicFeet) <= 0) return;
    void calculate();
    // Load the unified selectable charge catalog whenever the pricing book changes.
    // User selections are preserved by subsequent checkbox-triggered calculations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.id, destination, editing, pricingMode]);

  return (
    <div className="pricing-page">
      {bulkyCatalogIndex !== null && <BulkyCatalogPicker initialName={active?.services?.[bulkyCatalogIndex]?.name || ''} onClose={() => setBulkyCatalogIndex(null)} onSelect={item => { patchService(bulkyCatalogIndex, { name: item.name }); setBulkyCatalogIndex(null); }} />}
      <header className="pricing-heading">
        <div>
          <h1>Pricing</h1>
          <p>Local hourly rates and long-distance pricing books.</p>
        </div>

      </header>

      {error ? <div className="pricing-alert error">{error}</div> : null}
      {notice ? <div className="pricing-alert success">{notice}</div> : null}

      <div className="pricing-mode" aria-label="Pricing type">
        <button className="slds-button" type="button" aria-pressed={pricingMode === "local"} onClick={() => setPricingMode("local")}>Local</button>
        <button className="slds-button" type="button" aria-pressed={pricingMode === "long-distance"} onClick={() => setPricingMode("long-distance")}>Long Distance</button>
      </div>
      <div className="pricing-layout">
        <aside className="pricing-book-list">
          <label>Pricing book</label>
          <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            <option value="">Select a pricing book</option>
            {plans.map((row) => <option key={row.id} value={row.id}>{row.company_name} — {row.name}</option>)}
          </select>
          <div className="pricing-books-desktop">
            {plans.map((row) => (
              <button key={row.id} className={["slds-button", row.id === selectedId ? "active" : ""].filter(Boolean).join(" ")} onClick={() => setSelectedId(row.id)}>
                <strong>{row.company_name}</strong><span>{row.name}</span>
              </button>
            ))}
          </div>
        </aside>

        <main className="pricing-content">
          {pricingMode === "local" ? (
            selectedId ? <LocalPricing key={`${selectedId}:${jobContext?.job?.id || ""}`} planId={selectedId} companyName={plans.find(row => row.id === selectedId)?.company_name || ""} bookName={plans.find(row => row.id === selectedId)?.name || ""} job={jobContext ? { leadId: jobContext.lead?.id || "", jobId: jobContext.job?.id || "", name: jobContext.lead?.full_name || "", order: jobContext.job?.job_order || 1, volume: jobContext.lead?.volume ?? null, pickup: jobContext.job?.pickup_zip || "", delivery: jobContext.job?.delivery_zip || "", moveType: jobContext.move_type || "" } : undefined} services={active?.services || []} /> : <section className="pricing-card">{loading ? "Loading pricing?" : "Select a pricing book to set up Local pricing."}</section>
          ) : jobContext && jobContext.serviceability !== "supported" ? (
            <section className="pricing-card pricing-unavailable">
              <div className="pricing-unavailable-icon" aria-hidden="true">⌖</div>
              <div>
                <span className="eyebrow">Service area check</span>
                <h2>{jobContext.serviceability === "unsupported_pickup" ? "This pickup is outside our current service area" : "We couldn’t confirm the pickup service area"}</h2>
                <p>
                  {jobContext.serviceability === "unsupported_pickup"
                    ? `We don’t currently have a pricing book for pickups in ${jobContext.job.pickup_state}. Please confirm availability with dispatch before quoting this move.`
                    : "Add a valid pickup address or five-digit ZIP code to the job, then try Calculate Price again."}
                </p>
                <Link to={`/leads/${jobContext.lead.id}?job_id=${encodeURIComponent(jobContext.job.id)}`}>Return to the lead</Link>
              </div>
            </section>
          ) : loading || !active ? <div className="pricing-card">Loading pricing…</div> : (
            <>
              {jobContext ? (
                <section className="pricing-card pricing-job-context">
                  <div>
                    <span className="eyebrow">Pricing Job {jobContext.job.job_order}</span>
                    <h2>{jobContext.lead.full_name}</h2>
                    <p>{jobContext.job.pickup_zip || "Pickup not provided"} → {jobContext.job.delivery_zip || "Delivery not provided"}</p>
                  </div>
                  <div>
                    <span>{jobContext.job.move_date || "No move date"}</span>
                    <Link to={`/leads/${jobContext.lead.id}?job_id=${encodeURIComponent(jobContext.job.id)}`}>Back to lead</Link>
                  </div>
                </section>
              ) : null}
              <section className="pricing-card pricing-overview">
                <div>
                  <span className="eyebrow">{active.company_name}</span>
                  {editing ? <input className="pricing-title-input" value={active.name} onChange={(e) => patchDraft({ name: e.target.value })} /> : <h2>{active.name}</h2>}
                  <p>{active.pickup_regions || "Pickup coverage is described in the rules below."}</p>
                </div>
                {user?.role === "admin" && active && pricingMode === "long-distance" ? (
          <div className="pricing-actions">
            {editing ? (
              <>
                <button className="slds-button secondary" onClick={() => { setDraft(current => current && plan ? {...current, name: plan.name, fuel_percent: plan.fuel_percent, price_valid_days: plan.price_valid_days} : current); setEditing(false); }}>Cancel changes</button>
                <button className="slds-button primary" disabled={saving} onClick={() => void save()}>{saving ? "Saving…" : "Save changes"}</button>
              </>
            ) : <button className="slds-button primary" onClick={() => setEditing(true)}>Edit details</button>}
          </div>
        ) : null}
                <div className="pricing-kpis">
<div><span>Price valid for (days)</span>{editing ? <input aria-label="Price valid for (days)" type="number" min="1" max="3650" step="1" value={active.price_valid_days ?? 7} onChange={event => patchDraft({ price_valid_days: Number(event.target.value) })} /> : <strong>{active.price_valid_days ?? 7}</strong>}</div>
                  <div><span>Fuel</span>{editing ? <input type="number" step="0.1" value={active.fuel_percent ?? ""} onChange={(e) => patchDraft({ fuel_percent: e.target.value === "" ? null : Number(e.target.value) })} /> : <strong>{active.fuel_percent == null ? "See rules" : `${active.fuel_percent}%`}</strong>}</div>
                  <div><span>Destinations</span><strong>{destinations.length}</strong></div>
                  <div><span>Services</span><strong>{active.services.length}</strong></div>
                </div>
              </section>

              <PricingSection title="Pickup areas" count={active.pickup_areas?.length || 0} open={openSections.pickup} toggle={() => setOpenSections(s => ({ ...s, pickup: !s.pickup }))} onDoubleClick={() => startServiceEdit('pickup')} actions={serviceEditActions('pickup')}>
                <PickupAreasCard areas={active.pickup_areas || []} editing={editingSection('pickup')} onChange={pickup_areas => patchDraft({ pickup_areas })} />
              </PricingSection>

              <section className="pricing-card pricing-calculator">
                <div><span className="eyebrow">Job pricing</span><h2>Calculate price</h2></div>
                {jobContext && !destination ? (
                  <div className="pricing-inline-unavailable">
                    <strong>Delivery area not available</strong>
                    <span>{jobContext.job.delivery_state ? `No matching destination rate was found for this address in ${jobContext.job.delivery_state}. Check the delivery ZIP and pricing book.` : 'The delivery address could not be resolved. Check the address before calculating.'}</span>
                  </div>
                ) : null}
                <div className="pricing-calc-fields">
                  <label>Destination<select value={destination} onChange={(e) => { setDestination(e.target.value); calculationId.current++; setCalculating(false); setQuote(null); }}><option value="">Select a supported destination</option>{destinations.map((name) => <option key={name}>{name}</option>)}</select></label>
                  {!jobContext && active.services.some(isOriginFeesCard) && <label>Pickup address or ZIP<input value={pickupAddress} placeholder="Full address preferred" onChange={e => { setPickupAddress(e.target.value); calculationId.current++; setCalculating(false); setQuote(null); }} /></label>}
                  {!jobContext && active.services.some(isDeliveryFeesCard) && <label>Delivery address or ZIP<input value={deliveryAddress} placeholder="Full address preferred" onChange={e => { setDeliveryAddress(e.target.value); calculationId.current++; setCalculating(false); setQuote(null); }} /></label>}
                  {!jobContext?.job.move_date && active.services.some(isStorageCard) && <label>Pickup date<JobDatePicker value={storagePickupDate} onChange={value => { setStoragePickupDate(value); calculationId.current++; setCalculating(false); setQuote(null); }} /></label>}
                  {active.services.some(isStorageCard) && <label>Earliest delivery date<JobDatePicker value={availableDate || jobContext?.storage?.available_date || ''} onChange={value => { setAvailableDate(value); calculationId.current++; setCalculating(false); setQuote(null); }} /></label>}
                  {active.services.some(s => isElevatorCard(s) && JSON.parse(s.comments.slice('__elevator_pricing__:'.length)).enabled) && (['pickup','delivery'] as const).map(place => <label key={place}>{place === 'pickup' ? 'Pickup' : 'Delivery'} elevator<select value={elevatorValue(place) === null ? '' : elevatorValue(place) ? 'yes' : 'no'} onChange={e => { setElevatorAnswers(old => ({...old,[place]:e.target.value})); calculationId.current++; setCalculating(false); setQuote(null); }}><option value="">Choose</option><option value="yes">Yes</option><option value="no">No</option></select></label>)}
                  {active.services.some(s => isLongCarryCard(s) && JSON.parse(s.comments.slice('__long_carry_pricing__:'.length)).enabled) && (['pickup', 'delivery'] as const).map(place => <label key={place}>{place === 'pickup' ? 'Pickup' : 'Delivery'} carrying distance (feet)<input type="number" min="0" max="100000" step="1" value={carryFeet[place] ?? jobContext?.long_carry?.locations.find(row => row.location === place)?.distance_feet ?? ''} onChange={e => { setCarryFeet(old => ({ ...old, [place]: e.target.value })); calculationId.current++; setCalculating(false); setQuote(null); }} /></label>)}
                  {active.services.some(s => isStairsCard(s) && JSON.parse(s.comments.slice('__stairs_pricing__:'.length)).enabled) && (['pickup', 'delivery'] as const).map(place => <label key={place}>{place === 'pickup' ? 'Pickup' : 'Delivery'} outdoor/building flights<input type="number" min="0" max="1000" step="1" value={stairsFlights[place] ?? jobContext?.stairs?.locations.find(row => row.location === place)?.flights ?? ''} onChange={e => { setStairsFlights(old => ({ ...old, [place]: e.target.value })); calculationId.current++; setCalculating(false); setQuote(null); }} /></label>)}
                  <label>Cubic feet<input type="number" min="0" step="1" value={cubicFeet} onChange={(e) => { setCubicFeet(roundedCubicFeet(e.target.value)); calculationId.current++; setCalculating(false); setQuote(null); }} placeholder="e.g. 650" /></label>
                  <button className="slds-button primary" disabled={!destination || calculating} onClick={() => void calculate()}>{calculating ? "Calculating..." : "Calculate"}</button>
                </div>
                {quote ? (
                  <>
                    <div className="pricing-quote">
                      <div className="pricing-quote-header">
                        <div><span className="eyebrow">Price breakdown</span><h3>Detailed Price</h3></div>
                        <strong>{money(detailedTotal)}</strong>
                      </div>
                      <div className="pricing-quote-lines">
                        <div className="pricing-quote-line">
                          <div>
                            <strong>Transportation charge</strong>
                            <small>
                              {quote.match
                                ? `${cubicFeetValue(cubicFeet).toLocaleString()} cf × ${quote.match.rate == null ? quote.match.rate_text || "manual rate" : `${money(quote.match.rate)} / cf`} · ${quote.match.band_label}${quote.minimum_applied ? ` · ${money(quote.minimum)} minimum applied` : ""}`
                                : "No transportation rate matched"}
                            </small>
                          </div>
                          <div className="pricing-line-price"><b>{money(quote.base_price)}</b><button className="slds-button" type="button" onClick={() => addLineDiscount("transportation")}>+ Discount</button></div>
                        </div>
                        <label className="pricing-discount-choice">Transportation discount
                          <select aria-label="Transportation discount" value="" onChange={event => {
                            const rule = active.rules[Number(event.target.value)];
                            if (!rule) return;
                            setCustomDiscounts(rows => [...rows.filter(row => row.targetId !== 'transportation'), {
                              id: crypto.randomUUID(), targetId: 'transportation', title: rule.title,
                              type: rule.category.slice(9) as CustomDiscount['type'], value: Number(rule.description) || 0,
                            }]);
                          }}>
                            <option value="" disabled>Choose a price sheet discount</option>
                            {active.rules.map((rule, index) => isDiscountRule(rule) && <option key={rule.id || index} value={index}>{rule.title}</option>)}
                          </select>
                          <small>Applies to transportation only, including below the minimum. Fees and fuel stay unchanged. Use + Discount for a custom reduction.</small>
                        </label>
                        {lineDiscounts("transportation").map((discount) => (
                          <DiscountRow key={discount.id} discount={discount} originalAmount={discountTargets.transportation || 0} setDiscounts={setCustomDiscounts} />
                        ))}
                        {quote.charges.filter((charge) => charge.selected).map((charge) => (
                          <div key={`summary-${charge.id}`}>
                            <div className="pricing-quote-line">
                              <div>
                                <strong>{charge.name}</strong>
                                <small>{charge.description}</small>
                                {(charge.discount_amount || 0) > 0 && <small>Before discount: {money(charge.subtotal)}; Discount ({charge.discount_percent}%): -{money(charge.discount_amount)}</small>}
                                {charge.breakdown?.map((line, index) => (
                                  <span className="pricing-charge-breakdown" key={`${charge.id}-breakdown-${index}`}>
                                    <span>{line.label}</span><b>{money(line.amount)}</b>
                                  </span>
                                ))}
                              </div>
                              <div className="pricing-line-price"><b className={charge.amount < 0 ? "discount" : ""}>{charge.description.startsWith('Calculation pending: ') ? 'Pending' : money(charge.amount)}</b><button className="slds-button" type="button" onClick={() => addLineDiscount(`charge:${charge.id}`)}>+ Discount</button></div>
                            </div>
                            {lineDiscounts(`charge:${charge.id}`).map((discount) => (
                              <DiscountRow key={discount.id} discount={discount} originalAmount={discountTargets[`charge:${charge.id}`] || 0} setDiscounts={setCustomDiscounts} />
                            ))}
                          </div>
                        ))}
                        {customCharges.map((charge) => (
                          <div key={`custom-summary-${charge.id}`}>
                            <div className="pricing-quote-line">
                              <div><strong>{charge.title.trim() || "Custom charge"}</strong><small>Custom charge</small></div>
                              <div className="pricing-line-price"><b>{money(Math.max(0, Number(charge.amount) || 0))}</b><button className="slds-button" type="button" onClick={() => addLineDiscount(`custom:${charge.id}`)}>+ Discount</button></div>
                            </div>
                            {lineDiscounts(`custom:${charge.id}`).map((discount) => (
                              <DiscountRow key={discount.id} discount={discount} originalAmount={discountTargets[`custom:${charge.id}`] || 0} setDiscounts={setCustomDiscounts} />
                            ))}
                          </div>
                        ))}
                        <div className="pricing-quote-total"><strong>{quote.charges.some(charge => charge.description.startsWith('Calculation pending: ')) ? 'Partial estimate ? pending charges excluded' : 'Estimated Total'}</strong><b>{money(detailedTotal)}</b></div>
                      </div>
                      {quote.warning ? <p className="pricing-quote-warning" role="status">{quote.warning}</p> : null}
                      {jobContext && !editing && <div className="pricing-quote-actions"><button type="button" className="slds-button primary" disabled={savingPrice || calculating || detailedTotal <= 0 || quote.base_price == null} onClick={() => void savePrice()}>{savingPrice ? "Saving price..." : "Save price"}</button></div>}
                    </div>
                    <div className="pricing-charge-picker">
                      <div className="pricing-charge-heading">
                        <strong>Charges and adjustments</strong>
                        <span>Default charges are already selected</span>
                      </div>
                      {quote.charges.map((charge) => (
                        <article key={charge.id} className={charge.selected ? "selected" : ""}>
                          <label>
                            <input
                              type="checkbox"
                              checked={charge.selected}
                              disabled={charge.required || (charge.automatic && !charge.applies)}
                              onChange={(event) => {
                                const next = { ...selectedCharges, [charge.id]: event.target.checked };
                                setSelectedCharges(next);
                                void calculate({ selected: next });
                              }}
                            />
                            <span>
                              <strong>
                                {charge.name}
                                {charge.automatic ? <em>Automatic</em> : charge.default_selected ? <em>Default</em> : null}
                              </strong>
                              <small>{charge.description}</small>
                            </span>
                          </label>
                          {charge.calculation_type === "per_unit" || charge.calculation_type === "per_cf_month" ? (
                            <div className="pricing-charge-quantity">
                              <label>{charge.quantity_label || "Quantity"}</label>
                              <input
                                type="number"
                                min={charge.calculation_type === "per_cf_month" ? "1" : "0"}
                                step="1"
                                value={quantities[charge.id] ?? 1}
                                aria-label={charge.quantity_label || "Quantity"}
                                title={charge.quantity_label || "Quantity"}
                                onChange={(event) => {
                                  const next = { ...quantities, [charge.id]: Math.max(charge.calculation_type === "per_cf_month" ? 1 : 0, Number(event.target.value)) };
                                  setQuantities(next);
                                  void calculate({ quantities: next });
                                }}
                              />
                              {charge.free_months ? <small>{charge.free_months === 1 ? "1st month free" : `${charge.free_months} months free`}</small> : null}
                            </div>
                          ) : null}
                          {charge.calculation_type === "manual" && charge.selected ? (
                            <input
                              type="number"
                              min="0"
                              value={manualAmounts[charge.id] ?? 0}
                              aria-label="Manual amount"
                              title="Manual amount"
                              onChange={(event) => {
                                const next = { ...manualAmounts, [charge.id]: Number(event.target.value) };
                                setManualAmounts(next);
                                void calculate({ manual: next });
                              }}
                            />
                          ) : null}
                          <b>{charge.description.startsWith('Calculation pending: ') ? 'Pending' : charge.selected ? money(charge.amount) : 'Not added'}</b>
                        </article>
                      ))}
                      <div className="pricing-manual-adjustments">
                        <div className="pricing-manual-group">
                          <div className="pricing-manual-title">
                            <div><strong>Custom charges</strong><small>Add any charge that is not listed above.</small></div>
                            <button className="slds-button" type="button" onClick={() => setCustomCharges((rows) => [...rows, { id: crypto.randomUUID(), title: "", amount: 0 }])}>+ Add charge</button>
                          </div>
                          {customCharges.map((charge) => (
                            <div className="pricing-manual-row custom-charge" key={charge.id}>
                              <label>Title<input value={charge.title} placeholder="Charge title" onChange={(event) => setCustomCharges((rows) => rows.map((row) => row.id === charge.id ? { ...row, title: event.target.value } : row))} /></label>
                              <label>Amount<input type="number" min="0" step="0.01" value={charge.amount || ""} placeholder="0.00" onChange={(event) => setCustomCharges((rows) => rows.map((row) => row.id === charge.id ? { ...row, amount: Number(event.target.value) } : row))} /></label>
                              <button type="button" className="slds-button text-danger" aria-label="Remove custom charge" onClick={() => setCustomCharges((rows) => rows.filter((row) => row.id !== charge.id))}>Remove</button>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </>
                ) : null}
              </section>

              <PricingSection title="Transportation rates" count={rateRows.length} open={openSections.rates} toggle={() => setOpenSections((s) => ({ ...s, rates: !s.rates }))} onDoubleClick={() => startServiceEdit('rates')} actions={<>{serviceEditActions('rates')}{user?.role === 'admin' && <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={saving} onClick={() => { startServiceEdit('rates'); addDestination(); }}>+ Add destination</button>}</>}>
                <div className="pricing-table-toolbar"><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search destination or ZIP area" /><span>{bands.length} cubic-foot bands</span></div>
                <div className="pricing-rate-table-wrap">
                  <table className="pricing-rate-table">
                    <thead><tr><th>Destination</th><th>Area</th><th>Minimum</th>{bands.map((band) => <th key={band}>{band}</th>)}{editingSection('rates') || hasPendingRateGroups ? <th>Actions</th> : null}</tr></thead>
                    <tbody>
                      {rateRows.map((group) => {
                        const isPendingGroup = pendingRateGroupKeys.has(group.rowIds.join("|"));
                        const groupEditable = editingSection('rates') || isPendingGroup;
                        return (
                        <tr key={group.key} className={isPendingGroup ? "pricing-rate-row-pending" : undefined}>
                          <th>{groupEditable ? <input value={group.destination} placeholder="Destination or ZIP prefix" onChange={(e) => patchRateGroup(group.rowIds, { destination: e.target.value })} /> : <>{group.destination || "—"}</>}</th>
                          <td>{groupEditable ? <input className="destination-group-input" value={group.destinationGroup} placeholder="Area, e.g. East Coast" onChange={(e) => patchRateGroup(group.rowIds, { destination_group: e.target.value })} /> : group.destinationGroup || "—"}</td>
                          <td>{groupEditable ? <input type="text" inputMode="decimal" value={group.minimumText || (group.minimumPrice ?? "")} onChange={(e) => patchRateGroup(group.rowIds, { minimum_price: e.target.value === "" || Number.isNaN(Number(e.target.value)) ? null : Number(e.target.value), minimum_text: e.target.value })} /> : money(group.minimumPrice)}</td>
                          {bands.map((band) => {
                            const rate = group.rates.find((row) => row.band_label === band);
                            return <td key={band}>{!rate ? "—" : groupEditable ? <input type="text" inputMode="decimal" value={rate.rate_text || (rate.rate ?? "")} onChange={(e) => patchRate(rate.id, { rate: e.target.value === "" || Number.isNaN(Number(e.target.value)) ? null : Number(e.target.value), rate_text: e.target.value })} /> : rate.rate == null ? rate.rate_text : money(rate.rate)}</td>;
                          })}
                          {editingSection('rates') || isPendingGroup ? <td className="pricing-rate-actions"><button type="button" className="slds-button text-danger" onClick={() => removeRateGroup(group.rowIds)}>{isPendingGroup ? "Remove new row" : "Remove"}</button></td> : null}
                        </tr>
                      );})}
                      {!rateRows.length ? <tr><td colSpan={bands.length + (editingSection('rates') || hasPendingRateGroups ? 4 : 3)} className="pricing-rate-empty">No destinations match this search.</td></tr> : null}
                    </tbody>
                  </table>
                </div>
              </PricingSection>

              <PricingSection title="Additional stop pricing" count={active.services.filter(isExtraStopsCard).length} open={openSections.extraStops} toggle={() => setOpenSections(s => ({ ...s, extraStops: !s.extraStops }))} onDoubleClick={() => startServiceEdit('extraStops')} actions={serviceEditActions('extraStops')}>
                <ExtraStopsPricingCard services={active.services} editing={editingSection('extraStops')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Elevator pricing" count={active.services.filter(isElevatorCard).length} open={openSections.elevator} toggle={() => setOpenSections(s => ({ ...s, elevator: !s.elevator }))} onDoubleClick={() => startServiceEdit('elevator')} actions={serviceEditActions('elevator')}>
                <ElevatorPricingCard services={active.services} editing={editingSection('elevator')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Long carry pricing" count={active.services.filter(isLongCarryCard).length} open={openSections.longCarry} toggle={() => setOpenSections(s => ({ ...s, longCarry: !s.longCarry }))} onDoubleClick={() => startServiceEdit('longCarry')} actions={serviceEditActions('longCarry')}>
                <LongCarryPricingCard services={active.services} editing={editingSection('longCarry')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Stairs pricing" count={active.services.filter(isStairsCard).length} open={openSections.stairs} toggle={() => setOpenSections(s => ({ ...s, stairs: !s.stairs }))} onDoubleClick={() => startServiceEdit('stairs')} actions={serviceEditActions('stairs')}>
                <StairsPricingCard services={active.services} editing={editingSection('stairs')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Storage pricing" count={active.services.filter(isStorageCard).length} open={openSections.storage} toggle={() => setOpenSections(s => ({ ...s, storage: !s.storage }))} onDoubleClick={() => startServiceEdit('storage')} actions={serviceEditActions('storage')}>
                <StoragePricingCard services={active.services} editing={editingSection('storage')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Origin fees" count={active.services.filter(isOriginFeesCard).length} open={openSections.originFees} toggle={() => setOpenSections(s => ({ ...s, originFees: !s.originFees }))} onDoubleClick={() => startServiceEdit('originFees')} actions={serviceEditActions('originFees')}>
                <DeliveryFeesCard origin services={active.services} editing={editingSection('originFees')} onChange={services => patchDraft({ services })} />
              </PricingSection>
              <PricingSection title="Destination fees" count={active.services.filter(isDeliveryFeesCard).length} open={openSections.deliveryFees} toggle={() => setOpenSections(s => ({ ...s, deliveryFees: !s.deliveryFees }))} onDoubleClick={() => startServiceEdit('deliveryFees')} actions={serviceEditActions('deliveryFees')}>
                <DeliveryFeesCard services={active.services} editing={editingSection('deliveryFees')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Delivery shuttle" count={active.services.filter(isShuttleCard).length} open={openSections.shuttle} toggle={() => setOpenSections(s => ({ ...s, shuttle: !s.shuttle }))} onDoubleClick={() => startServiceEdit('shuttle')} actions={serviceEditActions('shuttle')}>
                <ShuttleCard services={active.services} editing={editingSection('shuttle')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Packing rates" count={4} open={openSections.packing} toggle={() => setOpenSections(s => ({ ...s, packing: !s.packing }))} onDoubleClick={() => startServiceEdit('packing')} actions={serviceEditActions('packing')}>
                <LongDistancePackingCard services={active.services} editing={editingSection('packing')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <PricingSection title="Materials" count={materialRows(active.services).length} open={openSections.materials} toggle={() => setOpenSections(s => ({ ...s, materials: !s.materials }))} onDoubleClick={() => startServiceEdit('materials')} actions={serviceEditActions('materials')}>
                <LongDistanceMaterialsCard services={active.services} editing={editingSection('materials')} onChange={services => patchDraft({ services })} />
              </PricingSection>

              <ItemMaterialsCard key={active.id} planId={active.id} blocked={saving} />
              <ItemSelectorsCard key={`selectors-${active.id}`} planId={active.id} blocked={saving} />

              <PricingSection title="Bulky items rates" count={bulkyItems.length} open={openSections.bulkyItems} toggle={() => setOpenSections((s) => ({ ...s, bulkyItems: !s.bulkyItems }))} onDoubleClick={() => startServiceEdit('bulkyItems')} actions={serviceEditActions('bulkyItems')}>
                <div className="pricing-services pricing-bulky-rates">
                  {bulkyItems.map((item) => {
                    const index = (active.services || []).indexOf(item);
                    const prices = bulkyItemPrices(item);
                    const handlingRate = Number(prices.handling);
                    return (
                      <article key={item.id || `bulky-${index}`}>
                        {editingSection('bulkyItems') ? (
                          <>
                            <button type="button" className="slds-button" onClick={() => setBulkyCatalogIndex(index)} aria-label={`Choose catalog item for ${item.name || 'new bulky item'}`}>{item.name || 'Choose catalog item'}</button>
                            <input type="text" inputMode="decimal" value={prices.handling} placeholder="Handling" onChange={(e) => patchBulkyItemPrice(index, "handling", e.target.value)} />
                            <input type="text" inputMode="decimal" value={prices.packing} placeholder="Packing" onChange={(e) => patchBulkyItemPrice(index, "packing", e.target.value)} />
                            <input type="text" inputMode="decimal" value={prices.crating} placeholder="Crating" onChange={(e) => patchBulkyItemPrice(index, "crating", e.target.value)} />
                            <button className="slds-button text-danger" onClick={() => removeService(index)}>Remove</button>
                          </>
                        ) : <><div><strong>{item.name}</strong><small>Handling {prices.handling || "—"} · Packing {prices.packing || "—"} · Crating {prices.crating || "—"}</small></div><b>{prices.handling && !Number.isNaN(handlingRate) ? money(handlingRate) : prices.handling || "—"}</b></>}
                      </article>
                    );
                  })}
                  {editingSection('bulkyItems') ? <button className="slds-button add-row" onClick={addBulkyItem}>+ Add bulky item</button> : null}
                  {!editingSection('bulkyItems') && bulkyItems.length === 0 ? <article><div><strong>No bulky item rates</strong></div><b>—</b></article> : null}
                </div>
              </PricingSection>

              <PricingSection title="Transportation discounts" count={(discountDraft || plan?.rules.filter(isDiscountRule) || []).length} open={discountOpen} toggle={() => setDiscountOpen(value => !value)} actions={user?.role === 'admin' && (discountDraft ? <>
                <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={savingDiscounts} onClick={() => { setDiscountDraft(null); setDiscountError(''); }}>Cancel changes</button>
                <button type="button" className="slds-button pricing-section-action pricing-section-text-action" disabled={savingDiscounts} onClick={() => void saveDiscounts()}>{savingDiscounts ? 'Saving...' : 'Save changes'}</button>
              </> : <button type="button" className="slds-button pricing-section-action" aria-label="Edit transportation discounts" title="Edit" onClick={() => { setDiscountDraft(structuredClone(plan?.rules.filter(isDiscountRule) || [])); setDiscountError(''); setDiscountOpen(true); }}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16 3 5 5L8 21H3v-5L16 3Z" /><path d="m13 6 5 5" /></svg></button>)}>
                <div className="pricing-discount-catalog">
                <p>Named discounts for reps to apply to an estimate. Fees are adjusted separately.</p>
                {discountError && <p role="alert">{discountError}</p>}
                {(discountDraft || plan?.rules.filter(isDiscountRule) || []).map((rule, index) => <div className="pricing-line-discount" key={rule.id || index}>
                  <label>Name<input disabled={!discountDraft || savingDiscounts} value={rule.title} placeholder="Military, Senior, Seasonal..." onChange={event => patchDiscount(index, { title: event.target.value })} /></label>
                  <label>Discount type<select disabled={!discountDraft || savingDiscounts} value={rule.category} onChange={event => patchDiscount(index, { category: event.target.value })}>
                    <option value="discount_amount">Amount off ($)</option><option value="discount_percent">Percent off (%)</option><option value="discount_rate">Reduced rate ($/cu ft)</option>
                  </select></label>
                  <label>Value<input disabled={!discountDraft || savingDiscounts} type="number" min="0" max={rule.category === 'discount_percent' ? 100 : undefined} step="0.01" value={rule.description} onChange={event => patchDiscount(index, { description: event.target.value })} /></label>
                  {discountDraft && <button className="slds-button text-danger" disabled={savingDiscounts} onClick={() => setDiscountDraft(rows => rows?.filter((_, i) => i !== index) || [])}>Remove</button>}
                </div>)}
                {discountDraft && <button type="button" className="slds-button add-row" disabled={savingDiscounts} onClick={() => setDiscountDraft(rows => [...(rows || []), { category: 'discount_amount', title: '', description: '0' }])}>+ Add discount</button>}
                </div>
              </PricingSection>
              <PricingSection title="Additional services & adjustments" count={pricingServices.length + catalogRules.length} open={openSections.services} toggle={() => setOpenSections((s) => ({ ...s, services: !s.services }))} actions={serviceEditActions('services')}>
                <div className="pricing-services pricing-services-editor">
                  {pricingServices.map((service) => {
                    const index = (active.services || []).indexOf(service);
                    return (
                    <article key={service.id || index}>
                      {editingSection('services') ? (
                        <>
                          <input value={service.name} onChange={(e) => patchService(index, { name: e.target.value })} />
                          <input value={service.rate_text} onChange={(e) => patchService(index, { rate_text: e.target.value })} />
                          <input value={service.comments} onChange={(e) => patchService(index, { comments: e.target.value })} />
                          <button className="slds-button text-danger" onClick={() => removeService(index)}>Remove</button>
                        </>
                      ) : <><div><strong>{service.name}</strong>{service.comments ? <small>{service.comments}</small> : null}</div><b>{service.rate_text || "See note"}</b></>}
                    </article>
                    );
                  })}
                  {catalogRules.map((rule) => {
                    const index = (active.rules || []).indexOf(rule);
                    return (
                    <article key={rule.id || `rule-${index}`} className="pricing-service-rule">
                      {editingSection('services') ? (
                        <>
                          <input value={rule.title} onChange={(e) => patchRule(index, { title: e.target.value })} />
                          <textarea value={rule.description} onChange={(e) => patchRule(index, { description: e.target.value })} />
                          <button className="slds-button text-danger" onClick={() => patchDraft({ rules: (draft?.rules || []).filter((_, idx) => idx !== index) })}>Remove</button>
                        </>
                      ) : (
                        <>
                          <div><strong>{rule.title || "Pricing adjustment"} <em>Adjustment</em></strong><small>{rule.description}</small></div>
                          <b>{rule.category === "exception" ? "Conditional" : "Included rule"}</b>
                        </>
                      )}
                    </article>
                    );
                  })}
                  {editingSection('services') ? <button className="slds-button add-row" onClick={() => patchDraft({ services: [...(draft?.services || []), { name: "", rate_text: "", comments: "" }] })}>+ Add service</button> : null}
                  {editingSection('services') ? <button className="slds-button add-row" onClick={() => patchDraft({ rules: [...(draft?.rules || []), { category: "general", title: "Pricing adjustment", description: "" }] })}>+ Add adjustment</button> : null}
                </div>
              </PricingSection>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function DiscountRow({
  discount,
  originalAmount,
  setDiscounts,
}: {
  discount: CustomDiscount & { amount: number };
  originalAmount: number;
  setDiscounts: React.Dispatch<React.SetStateAction<CustomDiscount[]>>;
}) {
  const patch = (change: Partial<CustomDiscount>) =>
    setDiscounts((rows) => rows.map((row) => row.id === discount.id ? { ...row, ...change } : row));

  return (
    <div className="pricing-line-discount">
      <label>
        Discount title
        <input value={discount.title} placeholder="Discount title" onChange={(event) => patch({ title: event.target.value })} />
      </label>
      <label>
        Type
        <select value={discount.type} onChange={(event) => patch({ type: event.target.value as CustomDiscount['type'] })}>
          <option value="amount">Amount ($)</option>
          <option value="percent">Percentage (%)</option>
          {discount.targetId === 'transportation' && <option value="rate">Reduced rate ($/cu ft)</option>}
        </select>
      </label>
      <label>
        {discount.type === "percent" ? "Percent" : discount.type === 'rate' ? 'New cu-ft rate' : "Amount off"}
        <input type="number" min="0" step="0.01" value={discount.value || ""} placeholder="0.00" onChange={(event) => patch({ value: Number(event.target.value) })} />
      </label>
      <div className="pricing-line-discount-value">
        <small>{discount.type === "percent" ? `${Number(discount.value) || 0}% of original ${money(originalAmount)}` : discount.type === 'rate' ? 'Lower transportation rate' : "Fixed discount"}</small>
        <b>−{money(discount.amount)}</b>
      </div>
      <button type="button" className="slds-button text-danger" aria-label="Remove discount" onClick={() => setDiscounts((rows) => rows.filter((row) => row.id !== discount.id))}>Remove</button>
      {discount.targetId !== 'transportation' && <button type="button" className="slds-button" onClick={() => patch({ type: 'percent', value: 100, title: discount.title || 'Fee waived' })}>Waive fee</button>}
    </div>
  );
}

function PricingSection({ title, count, open, toggle, onDoubleClick, actions, children }: { title: string; count: number; open: boolean; toggle: () => void; onDoubleClick?: () => void; actions?: React.ReactNode; children: React.ReactNode }) {
  return <section className="pricing-card pricing-section" onDoubleClick={onDoubleClick}><div className="pricing-section-heading"><button className="slds-button pricing-section-title" onClick={toggle}><span><strong>{title}</strong><small>{count}</small></span></button><div className="pricing-section-actions">{actions}<button className="slds-button pricing-section-toggle" onClick={toggle} aria-label={open ? `Collapse ${title}` : `Expand ${title}`}>{open ? "−" : "+"}</button></div></div>{open ? <div className="pricing-section-body">{children}</div> : null}</section>;
}
