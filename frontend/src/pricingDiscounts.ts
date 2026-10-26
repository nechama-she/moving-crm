export type Discount = { id: string; targetId: string; title: string; type: 'amount' | 'percent' | 'rate'; value: number };

export function calculateDiscounts(discounts: Discount[], targets: Record<string, number>, volume: number) {
  const remaining = { ...targets };
  return discounts.map(discount => {
    const base = Math.max(0, targets[discount.targetId] || 0);
    const value = Number.isFinite(discount.value) ? Math.max(0, discount.value) : 0;
    const requested = discount.type === 'rate'
      ? Math.max(0, base - value * Math.max(0, volume))
      : discount.type === 'percent' ? base * value / 100 : value;
    const amount = Math.round(Math.min(remaining[discount.targetId] || 0, requested) * 100) / 100;
    remaining[discount.targetId] = Math.max(0, (remaining[discount.targetId] || 0) - amount);
    return { ...discount, amount };
  });
}
