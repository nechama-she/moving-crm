// Writes src/aurora/aurora-dark-pages.css: dark-mode colors for the existing pages shown in the new look.
// Their colors are fixed in their style sheets and inline styles, so each light background, dark text
// and light border is mapped, by what it is used for, to the matching dark color setting
// (aurora-dark.css). Runs before every build so dark mode follows page style changes.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const src = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const output = join(src, 'aurora', 'aurora-dark-pages.css');
// Shown only in the classic look, or not part of any page.
const skipSheets = new Set(['App.css', 'GlobalLeadSearch.css']);

const luminance = (rgb) => {
  const [r, g, b] = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
function hueAndSaturation([r, g, b]) {
  [r, g, b] = [r / 255, g / 255, b / 255];
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0 };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: h * 60, s };
}
// Blues are the classic brand color, which the new look shows as its accent.
const family = (h) => (h < 18 || h >= 335 ? 'red' : h < 58 ? 'amber' : h < 170 ? 'green' : h < 250 ? 'accent' : 'purple');
const toneToken = (name, part) => (name === 'accent' ? { bg: '--aur-accent-soft', fg: '--aur-accent-ink', line: '--aur-accent-line' }[part] : `--aur-${name}-${part}`);

// The dark color setting for a light-mode color, or null when the color already works on dark.
// Near-whites and greys are told apart from tints by chroma (how much color there is), since
// saturation is high for barely-tinted whites such as #f3f5f8.
function darkToken(kind, rgb) {
  const L = luminance(rgb), { h, s } = hueAndSaturation(rgb);
  const chroma = (Math.max(...rgb) - Math.min(...rgb)) / 255;
  if (kind === 'background') {
    if (L < 0.55) return null; // strong fills (buttons, dark headers) keep their color and white text
    if (chroma < 0.035) return L > 0.985 ? '--aur-surface' : '--aur-subtle';
    return toneToken(family(h), 'bg');
  }
  if (kind === 'color') {
    if (L >= 0.3) return null; // light text sits on strong fills
    if (s < 0.25) return L < 0.035 ? '--aur-ink' : L < 0.1 ? '--aur-ink-2' : '--aur-muted';
    if (L < 0.03 && family(h) === 'accent') return '--aur-ink'; // navy headings
    return toneToken(family(h), 'fg');
  }
  if (L < 0.4) return null;
  if (chroma < 0.1) return L > 0.75 ? '--aur-line' : '--aur-line-strong';
  return toneToken(family(h), 'line');
}

const COLOR = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([^)]*\)|\bwhite\b/g;
function parseColor(text) {
  const t = text.toLowerCase();
  if (t === 'white') return [255, 255, 255];
  let m = t.match(/^#([0-9a-f]{3})$/);
  if (m) return [...m[1]].map((x) => parseInt(x + x, 16));
  m = t.match(/^#([0-9a-f]{6})$/);
  if (m) return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  m = t.match(/^rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*(?:[,/]\s*([\d.]+%?))?/);
  if (m && (m[4] === undefined || parseFloat(m[4]) >= (m[4].endsWith('%') ? 60 : 0.6))) return [+m[1], +m[2], +m[3]];
  return null; // see-through colors already blend with what is behind them
}
const kindOf = (prop) => (/^background(-color)?$/.test(prop) ? 'background' : prop === 'color' ? 'color'
  : /^(border(-(top|right|bottom|left))?(-color)?|outline(-color)?)$/.test(prop) ? 'border' : null);

function walk(dir, found = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) { if (name !== 'aurora' && name !== 'demo') walk(path, found); } else found.push(path);
  }
  return found;
}

// Splits one level of a style sheet into [head, body] blocks.
function blocks(css) {
  const found = [];
  for (let i = 0; i < css.length;) {
    const open = css.indexOf('{', i);
    if (open < 0) break;
    let depth = 1, j = open + 1;
    for (; j < css.length && depth; j++) depth += css[j] === '{' ? 1 : css[j] === '}' ? -1 : 0;
    found.push([css.slice(i, open).trim(), css.slice(open + 1, j - 1)]);
    i = j;
  }
  return found;
}
const declarations = (body) => body.split(';').map((raw) => {
  const k = raw.indexOf(':');
  return k < 0 ? null : [raw.slice(0, k).trim().toLowerCase(), raw.slice(k + 1).trim()];
}).filter(Boolean);

// What the new look already restyles itself ("selector|kind"); those keep the new look's choice.
const restyled = new Set();
function collectRestyled(css) {
  for (const [head, body] of blocks(css)) {
    if (head.startsWith('@media') || head.startsWith('@supports')) { collectRestyled(body); continue; }
    const kinds = new Set(declarations(body).map(([prop]) => kindOf(prop)).filter(Boolean));
    for (let selector of head.split(/,(?![^(]*\))/)) {
      selector = selector.trim().replace(/^\.aurora\s+(\.aur-main\s+)?/, '');
      const inner = selector.match(/^:is\((.*)\)$/);
      for (const one of inner ? inner[1].split(',') : [selector]) for (const kind of kinds) restyled.add(`${one.trim()}|${kind}`);
    }
  }
}
for (const name of ['aurora.css', 'aurora-theme.css']) collectRestyled(readFileSync(join(src, 'aurora', name), 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''));

function convertSheet(css) {
  const rules = [];
  for (const [head, body] of blocks(css)) {
    if (head.startsWith('@media') || head.startsWith('@supports')) {
      const inner = convertSheet(body);
      if (inner.length) rules.push(`${head} {\n${inner.map((r) => `  ${r.replace(/\n/g, '\n  ')}`).join('\n')}\n}`);
      continue;
    }
    if (head.startsWith('@')) continue;
    const selectors = head.split(/,(?![^(]*\))/).map((s) => s.trim()).filter(Boolean);
    if (selectors.some((s) => /^(:root|html|body)\b/.test(s))) continue;
    const out = [];
    for (const [prop, rawValue] of declarations(body)) {
      const kind = kindOf(prop);
      if (!kind || selectors.every((s) => restyled.has(`${s}|${kind}`))) continue;
      const value = rawValue.replace(/\s*!important$/, '');
      let changed = false;
      const next = value.replace(COLOR, (m) => {
        const rgb = parseColor(m), token = rgb && darkToken(kind, rgb);
        if (!token) return m;
        changed = true;
        return `var(${token})`;
      });
      if (!changed) continue;
      // A plain light background becomes a background color; gradients and images keep their shape.
      if (kind === 'background' && !/gradient|url\(/.test(next)) out.push(`background-color: ${next.match(/var\(--aur-[a-z-]+\)/)[0]}`);
      else out.push(`${prop}: ${next}`);
    }
    if (out.length) rules.push(`${selectors.map((s) => `html.aur-dark ${s}`).join(',\n')} { ${out.join('; ')}; }`);
  }
  return rules;
}

const files = walk(src);
const sections = [];
for (const file of files.filter((f) => f.endsWith('.css') && !skipSheets.has(f.split(/[\\/]/).pop())).sort()) {
  const rules = convertSheet(readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''));
  if (rules.length) sections.push(`/* ${file.slice(src.length).replace(/\\/g, '/')} */\n${rules.join('\n')}`);
}

// Inline styles: React writes them as e.g. style="background: rgb(255, 255, 255); color: rgb(...)".
const inline = new Map();
// A value runs to the next property or the end of the style object, so ternaries over several lines count.
const INLINE = /\b(background|backgroundColor|color|border|borderTop|borderBottom|borderLeft|borderRight|borderColor|outline)\s*:\s*([\s\S]{0,400}?)(?=,\s*[A-Za-z]+\s*:|\s*\})/g;
for (const file of files.filter((f) => f.endsWith('.tsx'))) {
  for (const [, key, value] of readFileSync(file, 'utf8').matchAll(INLINE)) {
    const kind = key.startsWith('background') ? 'background' : key === 'color' ? 'color' : 'border';
    const gradient = kind === 'background' && value.includes('gradient(');
    for (const hex of value.match(/#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/g) || []) {
      const rgb = parseColor(hex), token = darkToken(kind, rgb);
      if (!token) continue;
      const css = `rgb(${rgb.join(', ')})`;
      // A light gradient becomes a flat dark fill; the shorthand also clears the gradient image.
      const prop = gradient ? 'background' : kind === 'background' ? 'background-color' : kind === 'color' ? 'color' : 'border-color';
      const selectors = gradient ? [`[style*="gradient("][style*="${css}"]`]
        : kind === 'background' ? [`[style*="background: ${css}"]`, `[style*="background-color: ${css}"]`]
        : kind === 'color' ? [`[style^="color: ${css}"]`, `[style*="; color: ${css}"]`]
        // Boxes with a border on some sides only are written as border-color: currentcolor rgb(...) ...
        : [`[style*="solid ${css}"]`, `[style*="dashed ${css}"]`, `[style*="border-color:"][style*="${css}"]`];
      const group = inline.get(`${prop}|${token}`) || new Set();
      selectors.forEach((s) => group.add(s));
      inline.set(`${prop}|${token}`, group);
    }
  }
}
// Borders first, then backgrounds, then text, so a text color never loses to a border rule. Within
// gradients the plain surface goes first, so a tinted gradient keeps its tint.
const order = { 'border-color': 0, background: 1, 'background-color': 2, color: 3 };
const neutral = (key) => /--aur-(surface|subtle)$/.test(key) ? 0 : 1;
const inlineRules = [...inline].sort(([a], [b]) => order[a.split('|')[0]] - order[b.split('|')[0]] || neutral(a) - neutral(b) || a.localeCompare(b))
  .map(([key, selectors]) => {
    const [prop, token] = key.split('|');
    return `html.aur-dark :is(\n  ${[...selectors].sort().join(',\n  ')}\n) { ${prop}: var(${token}) !important; }`;
  });

const css = `/* Generated by scripts/build-dark-mode.mjs before each build. Do not edit; change the script or aurora-dark.css. */

${sections.join('\n\n')}

/* Inline styles */
${inlineRules.join('\n')}
`;
// An undefined color setting would quietly fall back to the text color (e.g. white borders).
const defined = new Set([...readFileSync(join(src, 'aurora', 'aurora-dark.css'), 'utf8').matchAll(/^\s*(--aur-[a-z0-9-]+):/gm)].map((m) => m[1]));
const missing = [...new Set([...css.matchAll(/var\((--aur-[a-z0-9-]+)\)/g)].map((m) => m[1]))].filter((name) => !defined.has(name));
if (missing.length) throw new Error(`aurora-dark.css has no dark value for ${missing.join(', ')}`);
writeFileSync(output, css);
