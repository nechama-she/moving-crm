// The move page assistant: a chat with BoxBot about this move only. BoxBot saves the customer's changes through
// the page's own API, and asks the page to open its signing windows; the customer signs there, never the chat.
import { Fragment, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { AssistantError, callAssistant, displayText, type AssistantConfig } from './assistantClient';
import type { AssistantMessage, AssistantMove, AssistantReply, AssistantStep, Audience, BotAction, PageScreen, SlotCard } from './assistantTypes';
import './MoveAssistant.css';

type Props = {
  config: AssistantConfig;
  audience: Audience;
  move: AssistantMove;
  steps: AssistantStep[];
  headers: Record<string, string>;
  // A screen of the page is open (inventory, questions, estimate, Bill of Lading): the window steps aside,
  // and comes back when the screen closes if it was open.
  hidden: boolean;
  onScreen: (screen: PageScreen) => void;
  onBotAction: (action: BotAction) => void;
  // After every answer: BoxBot may have saved something. The page's live updates bring BoxBot's saves; without them
  // the page loads its sections again.
  onReplied: () => void;
  // The page's session is no longer valid (401): the page shows its own verification.
  onSessionEnded: () => void;
  // The customer changed their main phone or email in the chat: the page verifies again with the new contact.
  onReverify: () => void;
};

const storage = {
  read(key: string) { try { return sessionStorage.getItem(key); } catch { return null; } },
  write(key: string, value: string) { try { sessionStorage.setItem(key, value); } catch { /* Shown again next time. */ } },
  remove(key: string) { try { sessionStorage.removeItem(key); } catch { /* Nothing kept. */ } },
};
// The window's size on a computer. It opens at its smallest and can only grow: up and to the left, by dragging its
// top-left corner or edges, or with the button in its head. This browser keeps the size for the next visit.
const SIZE_KEY = 'cm_assistant_size';
type Size = { width: number; height: number };
const kept = {
  read() {
    try {
      const value = JSON.parse(localStorage.getItem(SIZE_KEY) || 'null');
      return value && Number.isFinite(value.width) && Number.isFinite(value.height) ? value as Size : null;
    } catch { return null; }
  },
  write(size: Size | null) {
    try { if (size) localStorage.setItem(SIZE_KEY, JSON.stringify(size)); else localStorage.removeItem(SIZE_KEY); } catch { /* It opens at its smallest. */ }
  },
};
// The same limits as the CSS: 400 x up to 660 at the least; the screen less its margins at the most.
const smallest = (): Size => ({ width: 400, height: Math.min(660, window.innerHeight - 128) });
const largest = (): Size => ({ width: Math.max(400, window.innerWidth - 48), height: Math.max(smallest().height, window.innerHeight - 120) });
const between = (value: number, low: number, high: number) => Math.round(Math.min(Math.max(value, low), high));
function fit(size: Size): Size | null {
  const low = smallest(), high = largest();
  const next = { width: between(size.width, low.width, high.width), height: between(size.height, low.height, high.height) };
  return next.width <= low.width + 4 && next.height <= low.height + 4 ? null : next;
}
type Edge = 'corner' | 'left' | 'top';

const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

export default function MoveAssistant({ config, audience, move, steps, headers, hidden, onScreen, onBotAction, onReplied, onSessionEnded, onReverify }: Props) {
  const rep = audience === 'rep';
  // Open when the page was refreshed with the window open; closing it (not a page screen covering it) clears this.
  const openKey = `cm_assistant_open_${move.accessId}`;
  const [open, setOpen] = useState(() => storage.read(openKey) === '1');
  // Opened by a tap: the typing box takes the focus. Opened by itself, after a refresh or after a page screen,
  // it does not, so a phone keyboard does not pop up.
  const tapped = useRef(false);
  // The window has been open in this page view: closing it then keeps it closed until the next page load.
  const shown = useRef(open);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [quickReplies, setQuickReplies] = useState<string[]>([]);
  const [draft, setDraft] = useState('');
  const [thinking, setThinking] = useState(false);
  const [slow, setSlow] = useState(false);
  // Waiting for BoxBot's greeting: the typing bubble says so. It is a status line, not a message, so it is never
  // saved or sent to BoxBot, and the greeting replaces it.
  const [greeting, setGreeting] = useState(false);
  const opened = useRef(false);
  const resume = useRef(false);
  const request = useRef<AbortController | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const [size, setSize] = useState<Size | null>(() => kept.read());
  const [resizing, setResizing] = useState(false);

  // Leaving stops the request in flight; a window that comes back (React mounts it again) asks for the greeting again.
  useEffect(() => () => { request.current?.abort(); opened.current = false; }, []);

  // The window opens by itself 5 seconds after each page load (a refresh too, even after the customer closed it),
  // and not over one of the page's screens: it then waits until the screen closes.
  useEffect(() => {
    if (open || hidden || shown.current) return;
    const timer = window.setTimeout(() => setOpen(true), 5000);
    return () => clearTimeout(timer);
  }, [open, hidden]);

  useEffect(() => {
    if (!open) return;
    shown.current = true;
    storage.write(openKey, '1');
    // The first opening asks BoxBot for its greeting, or for the conversation so far.
    if (!opened.current) { opened.current = true; void talk({ open: true }); }
    if (tapped.current) { tapped.current = false; input.current?.focus({ preventScroll: true }); }
    document.documentElement.classList.add('ma-open');
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') close(); };
    window.addEventListener('keydown', escape);
    return () => { window.removeEventListener('keydown', escape); document.documentElement.classList.remove('ma-open'); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- talk() is read when the window opens, not a reason to run again.
  }, [open, openKey]);

  // A page screen opened (from the window or the page): step aside, and come back after it closes.
  useEffect(() => {
    if (hidden && open) { resume.current = true; setOpen(false); }
    else if (!hidden && resume.current) { resume.current = false; setOpen(true); }
  }, [hidden, open]);

  useEffect(() => {
    const box = log.current;
    if (box) box.scrollTo({ top: box.scrollHeight, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }, [messages, thinking, slow, open]);

  // A message can take several seconds, because BoxBot saves it to the page first.
  useEffect(() => {
    if (!thinking) { setSlow(false); return; }
    const timer = window.setTimeout(() => setSlow(true), 5000);
    return () => clearTimeout(timer);
  }, [thinking]);

  // Kept once a drag ends, not on every move.
  useEffect(() => { if (!resizing) kept.write(size); }, [size, resizing]);

  function startResize(event: ReactPointerEvent<HTMLElement>, edge: Edge) {
    const box = panel.current;
    if (!box || event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget;
    const start = { x: event.clientX, y: event.clientY, width: box.offsetWidth, height: box.offsetHeight };
    handle.setPointerCapture(event.pointerId);
    setResizing(true);
    const move = (moved: PointerEvent) => setSize(fit({
      width: edge === 'top' ? start.width : start.width + start.x - moved.clientX,
      height: edge === 'left' ? start.height : start.height + start.y - moved.clientY,
    }));
    const end = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', end);
      handle.removeEventListener('pointercancel', end);
      setResizing(false);
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
  }

  // Bigger: most of the screen, at a width that still reads well. Smaller: back to how it opens.
  function toggleSize() {
    setSize(current => current ? null : fit({ width: Math.min(760, window.innerWidth - 48), height: window.innerHeight - 120 }));
  }

  function close() {
    resume.current = false;
    storage.remove(openKey);
    setOpen(false);
    launcher.current?.focus({ preventScroll: true });
  }

  async function talk(what: { open: true } | { message: string }) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setThinking(true);
    setGreeting('open' in what);
    try {
      const answer = await callAssistant({ config, accessId: move.accessId, audience, headers, signal: controller.signal, ...what });
      if (controller.signal.aborted) return;
      show(answer, 'open' in what);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof AssistantError && error.kind === 'session') { onSessionEnded(); return; }
      const text = error instanceof AssistantError ? error.message : "I couldn't answer that just now. Please try again.";
      setMessages(current => [...current, { id: newId(), role: 'assistant', text, failed: { retry: 'open' in what ? { open: true } : what } }]);
    } finally {
      if (request.current === controller) { request.current = null; setThinking(false); setGreeting(false); }
    }
  }

  function show(answer: AssistantReply, opening: boolean) {
    const reply: AssistantMessage[] = answer.reply ? [{ id: newId(), role: 'assistant', text: answer.reply, cards: answer.cards }] : [];
    setMessages(current => opening && answer.history?.length ? [...answer.history, ...reply] : [...current, ...reply]);
    setQuickReplies(answer.quickReplies);
    if (!opening) onReplied();
    if (answer.reverify) { onReverify(); return; }
    if (answer.action) onBotAction(answer.action);
  }

  function send(value = draft) {
    const text = value.trim();
    if (!text || thinking) return;
    setMessages(current => [...current, { id: newId(), role: 'customer', text }]);
    setQuickReplies([]);
    setDraft('');
    if (input.current) input.current.style.height = '';
    void talk({ message: text });
  }

  function retry(failed: AssistantMessage) {
    if (!failed.failed || thinking) return;
    setMessages(current => current.filter(item => item !== failed));
    void talk(failed.failed.retry);
  }

  function screen(type: PageScreen) {
    // Picking files keeps the page in view, so the customer sees them upload.
    if (type === 'upload_files') close();
    onScreen(type);
  }

  const done = steps.filter(step => step.state === 'done').length;
  const left = steps.length - done;
  const company = move.company;
  const lastAssistant = [...messages].reverse().find(item => item.role === 'assistant' && !item.failed);

  return (
    <div className={`ma-root${hidden ? ' is-hidden' : ''}`}>
      <button ref={launcher} type="button" className={`ma-launcher${open ? ' is-open' : ''}`} aria-expanded={open} aria-controls="move-assistant"
        onClick={() => { if (open) close(); else { tapped.current = true; setOpen(true); } }}>
        <span className="ma-launcher-icon"><Icon name={open ? 'close' : 'chat'} size={22} /></span>
        <span className="ma-launcher-text">
          <strong>{rep ? 'Ask about this move' : 'Ask about your move'}</strong>
          <small>{left ? `${left} step${left === 1 ? '' : 's'} left` : 'All steps done'}</small>
        </span>
        {left > 0 && !open && <span className="ma-launcher-dot" aria-hidden="true" />}
      </button>

      {open && (
        <section ref={panel} id="move-assistant" className={`ma-panel${size ? ' is-large' : ''}${resizing ? ' is-resizing' : ''}`} role="dialog" aria-modal="false" aria-label={`${company.name} assistant`}
          style={size ? { '--ma-w': `${size.width}px`, '--ma-h': `${size.height}px` } as CSSProperties : undefined}>
          {(['top', 'left', 'corner'] as Edge[]).map(edge => (
            <div key={edge} className={`ma-resize is-${edge}`} aria-hidden="true" title={edge === 'corner' ? 'Drag to make the window bigger' : undefined}
              onPointerDown={event => startResize(event, edge)} onDoubleClick={() => setSize(null)}>
              {edge === 'corner' && <svg className="ma-grip" width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M9 13.5 13.5 9M9 18.5 18.5 9M9 23 23 9" /></svg>}
            </div>
          ))}
          <header className="ma-head">
            <span className="ma-avatar" aria-hidden="true">
              {company.logo ? <img src={company.logo} alt="" /> : (company.name || 'M').slice(0, 1)}
            </span>
            <div className="ma-head-text">
              <strong>Move assistant</strong>
              <small>{company.name}{rep && <span className="ma-pill" title="A separate conversation from the customer's.">Rep view</span>}</small>
            </div>
            {company.phone && <a className="ma-icon-btn" href={`tel:${company.phone}`} aria-label={`Call ${company.name}`} title={`Call ${company.phone}`}><Icon name="phone" size={18} /></a>}
            <button type="button" className="ma-icon-btn ma-size-btn" aria-label={size ? 'Make the window smaller' : 'Make the window bigger'}
              title={size ? 'Smaller' : 'Bigger'} onClick={toggleSize}><Icon name={size ? 'shrink' : 'grow'} size={18} /></button>
            <button type="button" className="ma-icon-btn" aria-label="Close assistant" onClick={close}><Icon name="close" size={18} /></button>
          </header>

          <nav className="ma-progress" aria-label="Your steps">
            <div className="ma-progress-top">
              <span>Your estimate</span>
              <small>{left ? `${done} of ${steps.length} done` : 'Complete'}</small>
            </div>
            <ol>
              {steps.map((step, index) => (
                <li key={step.id}>
                  <button type="button" className={`ma-step is-${step.state}`} disabled={!step.available} title={step.busy || step.status}
                    onClick={() => screen(STEP_SCREEN[step.id])}>
                    <span className="ma-step-mark" aria-hidden="true">{step.state === 'done' ? <Icon name="check" size={12} /> : index + 1}</span>
                    <span className="ma-step-text"><span>{step.label}</span><small>{step.busy || step.status}</small></span>
                  </button>
                </li>
              ))}
            </ol>
          </nav>

          <div className="ma-log" ref={log} role="log" aria-live="polite" aria-label="Conversation">
            {messages.map(item => (
              <div key={item.id} className={`ma-row is-${item.role}`}>
                <div className={`ma-bubble${item.failed ? ' is-failed' : ''}`}>
                  <RichText text={item.role === 'customer' ? displayText(item.text) : item.text} />
                  {item.failed && <button type="button" className="ma-retry" disabled={thinking} onClick={() => retry(item)}>Try again</button>}
                  {item.cards?.map((card, index) => <Slots key={index} card={card} disabled={thinking || item !== lastAssistant} onPick={start => send(`Book ${start}`)} />)}
                </div>
              </div>
            ))}
            {thinking && (
              <div className="ma-row is-assistant">
                <div className="ma-bubble ma-typing" aria-label="The assistant is typing"><i /><i /><i />
                  {greeting ? <span>Looking over your move details...</span> : slow && <span>Working on it. This can take a few seconds.</span>}</div>
              </div>
            )}
          </div>

          {!thinking && quickReplies.length > 0 && (
            <div className="ma-suggest" aria-label="Quick replies">
              {quickReplies.map(text => <button key={text} type="button" onClick={() => send(text)}>{text}</button>)}
            </div>
          )}

          <form className="ma-compose" onSubmit={event => { event.preventDefault(); send(); }}>
            {!move.readOnly && (
              <button type="button" className="ma-icon-btn" aria-label="Upload photos or videos" title="Upload photos or videos" onClick={() => screen('upload_files')}>
                <Icon name="clip" size={18} />
              </button>
            )}
            <label className="ma-sr" htmlFor="move-assistant-input">Message</label>
            <textarea id="move-assistant-input" ref={input} rows={1} value={draft} maxLength={1500} placeholder={rep ? 'Ask about this move' : 'Ask about your move or estimate'}
              onChange={event => {
                setDraft(event.target.value);
                event.target.style.height = '';
                event.target.style.height = `${Math.min(120, event.target.scrollHeight)}px`;
              }}
              onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }} />
            <button type="submit" className="ma-send" aria-label="Send" disabled={!draft.trim() || thinking}><Icon name="send" size={18} /></button>
          </form>
          <p className="ma-foot">{rep ? 'A separate conversation from the customer\'s. Changes are saved to this move.' : 'Changes you ask for are saved to this page. You always sign yourself.'}</p>
        </section>
      )}
    </div>
  );
}

const STEP_SCREEN: Record<AssistantStep['id'], PageScreen> = {
  inventory: 'open_inventory', services: 'open_services', estimate: 'open_estimate', bill_of_lading: 'open_bill_of_lading',
};

// Times for a video walkthrough, by day. A tap books the time by sending it as a message.
function Slots({ card, disabled, onPick }: { card: SlotCard; disabled: boolean; onPick: (start: string) => void }) {
  return (
    <div className="ma-slots" role="group" aria-label="Times for a video walkthrough">
      {card.days.map(day => (
        <div key={day.date || day.label} className="ma-slot-day">
          <span>{day.label}</span>
          <div>{day.slots.map(slot => <button key={slot.start} type="button" disabled={disabled} onClick={() => onPick(slot.start)}>{slot.label}</button>)}</div>
        </div>
      ))}
    </div>
  );
}

// Paragraphs, "- " lists and **bold**: all the formatting answers use. Plain text otherwise, never HTML.
function RichText({ text }: { text: string }) {
  return <>{text.split(/\n{2,}/).map((block, index) => {
    const lines = block.split('\n');
    const items = lines.filter(line => /^\s*[-*] /.test(line));
    if (items.length && items.length === lines.filter(line => line.trim()).length)
      return <ul key={index}>{items.map((line, i) => <li key={i}>{bold(line.replace(/^\s*[-*] /, ''))}</li>)}</ul>;
    const head = lines.filter(line => !/^\s*[-*] /.test(line));
    return <Fragment key={index}>
      {head.length > 0 && <p>{head.map((line, i) => <Fragment key={i}>{i > 0 && <br />}{bold(line)}</Fragment>)}</p>}
      {items.length > 0 && <ul>{items.map((line, i) => <li key={i}>{bold(line.replace(/^\s*[-*] /, ''))}</li>)}</ul>}
    </Fragment>;
  })}</>;
}
function bold(line: string): ReactNode {
  return line.split(/(\*\*[^*]+\*\*)/).map((part, i) => part.startsWith('**') && part.endsWith('**') && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong> : part);
}

function Icon({ name, size }: { name: 'chat' | 'close' | 'phone' | 'clip' | 'send' | 'check' | 'grow' | 'shrink'; size: number }) {
  const paths: Record<typeof name, ReactNode> = {
    chat: <><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12Z" /><path d="M8.5 11h.01M12 11h.01M15.5 11h.01" strokeWidth="2.6" /></>,
    close: <path d="M6 6l12 12M18 6 6 18" />,
    phone: <path d="M5 4h3.5l1.8 4.4-2.2 1.4a11 11 0 0 0 6.1 6.1l1.4-2.2L20 15.5V19a1.5 1.5 0 0 1-1.6 1.5A16.5 16.5 0 0 1 3.5 5.6 1.5 1.5 0 0 1 5 4Z" />,
    clip: <path d="m20 11.5-7.8 7.8a5 5 0 0 1-7.1-7.1l8.2-8.2a3.4 3.4 0 0 1 4.8 4.8l-8.2 8.2a1.7 1.7 0 0 1-2.4-2.4l7.6-7.6" />,
    send: <path d="M5 12h13M12 5l7 7-7 7" />,
    check: <path d="m5 12.5 4.5 4.5L19 7.5" strokeWidth="3" />,
    grow: <path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7" />,
    shrink: <path d="M19 10h-5V5M14 10l6-6M5 14h5v5M10 14l-6 6" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
