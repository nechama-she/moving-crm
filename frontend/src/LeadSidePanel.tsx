import { useEffect, useRef, useState, type ReactNode } from 'react';
import './LeadSidePanel.css';

// An action opens its own panel (e.g. estimate, files). `panelSelector` finds that panel so a hover
// preview can stay open while the pointer is over it and close once the pointer leaves.
export type LeadSideAction = {
  key: string; label: string; title: string; icon: ReactNode;
  open: () => void; close: () => void; panelSelector: string;
};

const TAB_LABELS = { conversations: 'Inbox', activity: 'Tasks' } as const;
const TAB_TITLES = { conversations: 'Communications: calls, texts and messages', activity: 'Tasks' } as const;
const OPEN_DELAY = 180;
const CLOSE_DELAY = 350;

// The drawer tabs need communications access; the action buttons (estimate, files) open their own dialogs.
export default function LeadSidePanel({ active, onSelect, tasksRequested, showTabs = true, actions = [], children }: {
  active: 'conversations' | 'activity' | 'logs'; onSelect: (tab: 'conversations' | 'activity') => void;
  tasksRequested: boolean; showTabs?: boolean; actions?: LeadSideAction[]; children?: ReactNode;
}) {
  const [open, setOpen] = useState(showTabs && tasksRequested);
  const [pinned, setPinned] = useState(showTabs && tasksRequested);
  const [previewAction, setPreviewAction] = useState<LeadSideAction | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const actionButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const cancel = () => { if (timer.current) clearTimeout(timer.current); };
  useEffect(() => { if (showTabs && tasksRequested) { setOpen(true); setPinned(true); } }, [showTabs, tasksRequested]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  function close() { cancel(); setOpen(false); setPinned(false); }
  // Hover previews only where the drawer floats beside the page; on narrow or touch screens it
  // covers the page, so moving the pointer away could never close it.
  const canPreview = () => window.matchMedia('(hover: hover) and (min-width: 701px)').matches;

  // While an action is only previewed, its panel (and backdrop) covers the rail, so follow the
  // pointer over the whole document: keep it open over the button or the panel, close it elsewhere.
  // Clicking or typing inside the panel turns the preview into a normal open panel.
  useEffect(() => {
    if (!previewAction) return;
    let closeTimer: ReturnType<typeof setTimeout> | null = null;
    const stopClosing = () => { if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; } };
    const onMove = (event: PointerEvent) => {
      const target = event.target as Element | null;
      const button = actionButtons.current[previewAction.key]?.getBoundingClientRect();
      const overButton = !!button && event.clientX >= button.left && event.clientX <= button.right
        && event.clientY >= button.top && event.clientY <= button.bottom;
      if (overButton || target?.closest(previewAction.panelSelector)) stopClosing();
      else if (!closeTimer) closeTimer = setTimeout(() => { previewAction.close(); setPreviewAction(null); }, CLOSE_DELAY);
    };
    const pin = (event: Event) => {
      if ((event.target as Element | null)?.closest(previewAction.panelSelector)) { stopClosing(); setPreviewAction(null); }
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerdown', pin, true);
    document.addEventListener('keydown', pin, true);
    return () => {
      stopClosing();
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerdown', pin, true);
      document.removeEventListener('keydown', pin, true);
    };
  }, [previewAction]);

  const title = active === 'activity' ? 'Tasks' : 'Inbox';
  return <div className="lead-side-tools" onMouseEnter={cancel} onMouseLeave={() => {
    cancel(); if (!pinned) timer.current = setTimeout(() => setOpen(false), CLOSE_DELAY);
  }} onKeyDown={event => { if (event.key === 'Escape') close(); }}>
    <nav className="lead-side-rail" aria-label="Lead tools">
      {showTabs ? (['conversations', 'activity'] as const).map(tab => <button type="button" key={tab}
        aria-label={TAB_TITLES[tab]} title={TAB_TITLES[tab]}
        aria-expanded={open && active === tab} aria-controls="lead-side-drawer"
        onMouseEnter={() => { cancel(); if (!pinned && canPreview()) timer.current = setTimeout(() => { onSelect(tab); setOpen(true); }, OPEN_DELAY); }}
        onClick={() => { cancel(); onSelect(tab); setOpen(true); setPinned(true); }}>
        <svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
          {tab === 'activity' ? <><rect x="5" y="4" width="15" height="17" rx="2"/><path d="M9 4V2h7v2M8 10l2 2 3-3m2 2h2M8 16l2 2 3-3m2 2h2"/></> : <path d="M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0Z"/>}
        </svg>
        <span>{TAB_LABELS[tab]}</span>
      </button>) : null}
      {actions.map(action => <button type="button" key={action.key} aria-label={action.title} title={action.title}
        ref={element => { actionButtons.current[action.key] = element; }}
        onMouseEnter={() => {
          cancel();
          if (pinned || !canPreview()) return;
          timer.current = setTimeout(() => { close(); action.open(); setPreviewAction(action); }, OPEN_DELAY);
        }}
        onMouseLeave={cancel}
        onClick={() => { close(); setPreviewAction(null); action.open(); }}>
        {action.icon}
        <span>{action.label}</span>
      </button>)}
    </nav>
    {showTabs ? <aside id="lead-side-drawer" className="lead-side-drawer" hidden={!open} aria-label={title}>
      <header><div><strong>{title}</strong><small>{pinned ? 'Pinned open' : 'Click an icon to pin open'}</small></div>
        <button type="button" onClick={close} aria-label="Close panel"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
      </header>
      <div className="lead-side-content" onFocusCapture={() => setPinned(true)} onPointerDown={() => setPinned(true)}>{children}</div>
    </aside> : null}
  </div>;
}
