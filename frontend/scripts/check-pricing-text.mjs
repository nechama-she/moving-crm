// Guard pricing text against lossy encoding and previously damaged UI labels.
import { readFileSync } from 'node:fs';

const files = ['../../backend/local_pricing.py', '../src/LocalPricing.tsx'];
const invalidText = /\uFFFD|\u00c3[\u0080-\u00bf]|\u00e2\u20ac|movers \?|Loading local pricing\?|Calculating estimate\?|Saving\?|["']\?["']/;
for (const file of files) {
  const bytes = readFileSync(new URL(file, import.meta.url));
  const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (invalidText.test(text)) {
    throw new Error(`Damaged pricing text in ${file}. Save as UTF-8 and repair the affected label.`);
  }
}
