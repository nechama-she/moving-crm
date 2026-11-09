// Motion for the new look: page transitions, the sliding sidebar highlight, the circular theme reveal and
// counting numbers. Built on the browser's own View Transitions and Web Animations; everything turns
// itself off when the person's system asks for reduced motion.
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

export const EASE_OUT = "cubic-bezier(0.215, 0.61, 0.355, 1)";
export const EASE_IN_OUT = "cubic-bezier(0.645, 0.045, 0.355, 1)";

export const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

type ViewTransition = { ready: Promise<void>; finished: Promise<void> };
type TransitionDocument = Document & { startViewTransition?: (update: () => void) => ViewTransition };

/** Runs a DOM update as a view transition of the given kind ("page", "theme"), or directly when unsupported. */
export function withViewTransition(kind: string, update: () => void): ViewTransition | null {
  const doc = document as TransitionDocument;
  if (!doc.startViewTransition || reducedMotion()) {
    update();
    return null;
  }
  const root = document.documentElement;
  // The kind selects the CSS for this transition (aurora.css, "View transitions").
  root.dataset.vt = kind;
  const transition = doc.startViewTransition(() => flushSync(update));
  transition.finished.finally(() => { if (root.dataset.vt === kind) delete root.dataset.vt; });
  return transition;
}

/** Reveals the new theme as a circle growing from the clicked control. */
export function revealFrom(transition: ViewTransition | null, origin?: Element | null) {
  if (!transition) return;
  const box = origin?.getBoundingClientRect();
  const x = box ? box.left + box.width / 2 : 40;
  const y = box ? box.top + box.height / 2 : innerHeight - 40;
  const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  transition.ready.then(() => document.documentElement.animate(
    { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
    { duration: 520, easing: EASE_IN_OUT, pseudoElement: "::view-transition-new(root)" },
  )).catch(() => {});
}

/**
 * Moves the sidebar highlight to the active link. The edge in the direction of travel leads quickly and the
 * other follows a little later, so the highlight stretches toward the new item and settles there.
 */
export function slideHighlight(highlight: HTMLElement, target: HTMLElement | null, animate: boolean) {
  if (!target) {
    highlight.style.opacity = "0";
    return;
  }
  // Measured on screen against the highlight's container, whatever the link's own positioned parents are.
  const box = highlight.parentElement!.getBoundingClientRect(), link = target.getBoundingClientRect();
  const left = link.left - box.left, top = link.top - box.top;
  const next = { top, bottom: box.height - top - link.height };
  // Start from where it is now, even mid-way through a previous move.
  const style = getComputedStyle(highlight);
  const prev = { top: parseFloat(style.top), bottom: parseFloat(style.bottom) };
  highlight.getAnimations().forEach(animation => animation.cancel());
  const wasHidden = highlight.style.opacity === "0" || !highlight.style.top;
  Object.assign(highlight.style, { top: `${next.top}px`, bottom: `${next.bottom}px`, left: `${left}px`, width: `${link.width}px`, opacity: "1" });
  if (!animate || wasHidden || reducedMotion() || (prev.top === next.top && prev.bottom === next.bottom)) return;
  const down = next.top > prev.top;
  const [lead, trail] = down ? (["bottom", "top"] as const) : (["top", "bottom"] as const);
  highlight.animate({ [lead]: [`${prev[lead]}px`, `${next[lead]}px`] }, { duration: 360, easing: EASE_OUT });
  highlight.animate({ [trail]: [`${prev[trail]}px`, `${next[trail]}px`] }, { duration: 550, easing: EASE_IN_OUT });
}

const EXPO_OUT = "cubic-bezier(0.16, 1, 0.3, 1)";
const SOFT_OUT = "cubic-bezier(0.165, 0.84, 0.44, 1)";
const POP = "cubic-bezier(0.34, 1.9, 0.64, 1)";
// How long after opening a page content that arrives (lazy pages, loaded data) is still built in.
const REVEAL_WINDOW = 2500;
const NUMBER = /^\s*([$]?)([\d,]+(?:\.\d+)?)(%?)\s*$/;
const ROWS = "tbody > tr, .aur-convo, .aur-thread-row, .aur-set-tile";

/**
 * Builds a page in when it opens: the heading rises letter by letter, cards rise one after another,
 * then rows and list items, small badges pop and big numbers count up. Works on any page by what
 * things look like (a card is a framed, rounded box), so the existing pages get it too.
 * Returns a cleanup for when the page changes.
 */
export function revealPage(main: HTMLElement): () => void {
  if (reducedMotion()) return () => {};
  const seen = new WeakSet<Element>();
  const drawn = new WeakSet<Element>();
  const restores: Array<() => void> = [];
  const opened = performance.now();
  let frame = 0;

  const pass = () => {
    frame = 0;
    // Content that arrives later starts its own sequence, a little after the page's first one.
    const start = performance.now() - opened < 120 ? 0 : 60;
    const cards: HTMLElement[] = [], rows: HTMLElement[] = [];
    collect(main, cards, rows, seen);
    const heading = main.querySelector<HTMLElement>("h1");
    if (heading && !seen.has(heading) && onScreen(heading)) {
      seen.add(heading);
      const restore = splitLetters(heading, start);
      if (restore) restores.push(restore);
      // The label above and the line below the heading rise in just behind it.
      [...(heading.parentElement?.children || [])].forEach((el, i) => {
        if (el !== heading && el instanceof HTMLElement && !el.querySelector("button, select, input")) el.animate(
          [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }],
          { duration: 550, delay: start + 140 + i * 40, easing: EASE_OUT, fill: "backwards" });
      });
    }
    const cardStep = Math.min(60, 600 / Math.max(1, cards.length));
    cards.forEach((card, i) => {
      const delay = start + 80 + i * cardStep;
      card.animate([{ opacity: 0, transform: "translateY(26px) scale(0.985)" }, { opacity: 1, transform: "none" }],
        { duration: 800, delay, easing: EXPO_OUT, fill: "backwards" });
      card.querySelectorAll<HTMLElement>(".aur-kpi-delta, .aur-pill, .aur-stage").forEach((badge, j) => {
        if (j < 6 && !badge.closest(ROWS)) badge.animate([{ opacity: 0, transform: "scale(0.6)" }, { opacity: 1, transform: "none" }],
          { duration: 600, delay: delay + 320 + j * 50, easing: POP, fill: "backwards" });
      });
      countNumbers(card, delay + 100);
      const lines = chartLines(card).filter(line => !drawn.has(line));
      const lineStep = Math.min(70, 500 / Math.max(1, lines.length));
      lines.forEach((line, j) => { drawn.add(line); drawLine(line, delay + 120 + j * lineStep, 1100); });
    });
    // Charts that arrive inside a card already on screen (it was loading) draw too.
    const late = chartLines(main).filter(line => !drawn.has(line));
    const lateStep = Math.min(90, 700 / Math.max(1, late.length));
    late.forEach((line, j) => { drawn.add(line); drawLine(line, start + 150 + j * lateStep, 1200); });
    const rowStep = Math.min(35, 500 / Math.max(1, rows.length));
    rows.forEach((row, i) => {
      const tile = row.classList.contains("aur-set-tile");
      row.animate(tile
        ? [{ opacity: 0, transform: `translateY(40px) rotate(${i % 2 ? 2.5 : -2.5}deg) scale(0.95)` }, { opacity: 1, transform: "none" }]
        : [{ opacity: 0, transform: "translateY(12px)" }, { opacity: 1, transform: "none" }],
      { duration: tile ? 850 : 550, delay: start + (cards.length ? 300 : 80) + i * rowStep, easing: tile ? "cubic-bezier(0.34, 1.4, 0.64, 1)" : EASE_OUT, fill: "backwards" });
    });
  };

  pass();
  const observer = new MutationObserver(() => {
    if (performance.now() - opened > REVEAL_WINDOW) { observer.disconnect(); return; }
    if (!frame) frame = requestAnimationFrame(pass);
  });
  observer.observe(main, { childList: true, subtree: true });
  const stop = window.setTimeout(() => observer.disconnect(), REVEAL_WINDOW);
  // Later on, a chart line that appears (a month turned back on in a legend) draws itself too.
  const lineObserver = new MutationObserver(records => {
    if (performance.now() - opened < REVEAL_WINDOW) return;
    for (const record of records) for (const node of record.addedNodes) {
      if (!(node instanceof Element)) continue;
      for (const line of chartLines(node.matches("polyline, path") ? node.parentElement ?? node : node)) {
        if (!drawn.has(line)) { drawn.add(line); drawLine(line, 0, 700); }
      }
    }
  });
  lineObserver.observe(main, { childList: true, subtree: true });
  return () => {
    observer.disconnect();
    lineObserver.disconnect();
    window.clearTimeout(stop);
    cancelAnimationFrame(frame);
    restores.forEach(restore => restore());
  };
}

const onScreen = (el: Element) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < innerHeight + 80 && r.bottom > -80; };

// Outermost cards, plus the rows inside them, top to bottom. Boxes inside a card build in with it;
// off-screen things just appear.
function collect(root: Element, cards: HTMLElement[], rows: HTMLElement[], seen: WeakSet<Element>, inCard = false) {
  for (const child of root.children) {
    if (!(child instanceof HTMLElement) || child.matches(".impersonation-banner")) continue;
    if (child.matches(ROWS)) {
      if (!seen.has(child)) { seen.add(child); if (onScreen(child)) rows.push(child); }
      continue;
    }
    const style = getComputedStyle(child);
    if (style.display === "none" || style.position === "fixed") continue;
    const card = !inCard && isCard(child, style);
    if (card && !seen.has(child)) {
      seen.add(child);
      if (onScreen(child)) cards.push(child);
    }
    collect(child, cards, rows, seen, inCard || card);
  }
}

// A card is a filled, framed, rounded box of a reasonable size.
function isCard(el: HTMLElement, style: CSSStyleDeclaration) {
  const box = el.getBoundingClientRect();
  if (box.width < 120 || box.height < 40 || box.width > innerWidth * 0.97) return false;
  const filled = style.backgroundColor !== "rgba(0, 0, 0, 0)" || style.backgroundImage !== "none";
  const framed = (style.borderTopStyle !== "none" && parseFloat(style.borderTopWidth) > 0) || style.boxShadow !== "none";
  return filled && framed && parseFloat(style.borderTopLeftRadius) >= 6;
}

// Splits a plain-text heading into letters that rise from behind a mask; puts the original text back after.
function splitLetters(heading: HTMLElement, start: number) {
  const nodes = [...heading.childNodes];
  // Only a heading that is one plain text: React then only ever updates that text node, which is put back.
  if (nodes.length !== 1 || nodes[0].nodeType !== Node.TEXT_NODE) return null;
  const text = heading.textContent || "";
  if (!text.trim() || text.length > 60) return null;
  heading.setAttribute("aria-label", text.trim());
  const letters: HTMLElement[] = [];
  const parts = text.split(/(\s+)/).map(part => {
    if (/^\s+$/.test(part)) return document.createTextNode(part);
    const word = Object.assign(document.createElement("span"), { className: "aur-split-word" });
    word.setAttribute("aria-hidden", "true");
    for (const ch of part) letters.push(word.appendChild(Object.assign(document.createElement("span"), { className: "aur-split-ch", textContent: ch })));
    return word;
  });
  heading.replaceChildren(...parts);
  const step = Math.min(22, 500 / Math.max(1, letters.length));
  const animations = letters.map((letter, i) => letter.animate(
    [{ transform: "translateY(115%) rotate(6deg)" }, { transform: "none" }],
    { duration: 850, delay: start + i * step, easing: SOFT_OUT, fill: "backwards" }));
  let restored = false;
  const restore = () => {
    if (restored) return;
    restored = true;
    // The original text nodes go back, so React keeps updating the same nodes it rendered.
    heading.replaceChildren(...nodes);
    heading.removeAttribute("aria-label");
  };
  Promise.all(animations.map(a => a.finished)).then(restore, restore);
  return restore;
}

// Lines of a chart: unfilled strokes inside an SVG that is chart-sized (icons are small), in drawing order.
function chartLines(scope: Element) {
  return [...scope.querySelectorAll<SVGGeometryElement>("svg polyline, svg path")].filter(line => {
    const svg = line.ownerSVGElement;
    if (!svg || svg.getBoundingClientRect().width < 200 || line.closest(".aur-spark")) return false;
    const style = getComputedStyle(line);
    return style.fill === "none" && style.stroke !== "none" && line.getTotalLength() > 40;
  });
}

// Draws a line from its start to its end.
function drawLine(line: SVGGeometryElement, delay: number, duration: number) {
  const length = line.getTotalLength();
  // The gap is longer than the line, so not even a rounded line end shows before the line starts.
  const dash = `${length} ${length + 20}`;
  line.animate([{ strokeDasharray: dash, strokeDashoffset: length + 10 }, { strokeDasharray: dash, strokeDashoffset: 0 }],
    { duration, delay, easing: "cubic-bezier(0.455, 0.03, 0.515, 0.955)", fill: "backwards" });
}

// Big numbers inside a card count up to their value. Stops if the page changes the number meanwhile.
function countNumbers(card: HTMLElement, delay: number) {
  const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
  let counted = 0;
  for (let node = walker.nextNode() as Text | null; node && counted < 8; node = walker.nextNode() as Text | null) {
    const parent = node.parentElement;
    const match = node.nodeValue?.match(NUMBER);
    if (!parent || !match || parent.closest(".aur-kpis, tbody, select, option, button, input") || parseFloat(getComputedStyle(parent).fontSize) < 18) continue;
    const target = Number(match[2].replace(/,/g, ""));
    if (!(target >= 10)) continue;
    counted++;
    const original = node.nodeValue!, decimals = (match[2].split(".")[1] || "").length, textNode = node;
    const format = (n: number) => `${match[1]}${n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: match[2].includes(",") })}${match[3]}`;
    let written = format(0);
    textNode.nodeValue = written;
    const begin = performance.now() + delay;
    const tick = (now: number) => {
      if (textNode.nodeValue !== written) return; // the page updated it: leave the page's value
      const t = Math.max(0, Math.min(1, (now - begin) / 1100));
      written = t >= 1 ? original : format(target * (1 - (1 - t) ** 3));
      textNode.nodeValue = written;
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}

/** A number that counts from its previous value (zero at first) to the new one. */
export function useCountUp(value: number | undefined, duration = 800) {
  const [shown, setShown] = useState(value ?? 0);
  const from = useRef(0);
  useEffect(() => {
    if (value === undefined) return;
    if (reducedMotion()) { setShown(value); from.current = value; return; }
    const start = performance.now(), begin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const current = begin + (value - begin) * (1 - (1 - t) ** 3);
      setShown(current);
      from.current = current;
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return shown;
}
