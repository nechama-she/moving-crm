const PATHS = {
  leads: "M9 4.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 1 0 0-7M2.5 20c.8-3.5 3.4-5.5 6.5-5.5s5.7 2 6.5 5.5M16 4.5a3.5 3.5 0 0 1 0 7M18 14.8c1.9.7 3.1 2.6 3.5 5.2",
  inbox: "M3 13h5l1.5 3h5L16 13h5M5 5h14l2 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z",
  queue: "M4 6h16M4 12h10M4 18h6M17 15l2 2 3-4",
  outreach: "M3 11l15-6v14L3 13zM7 13v5a2 2 0 0 0 4 0v-4",
  duplicate: "M8 8h11v11H8zM5 16V5h11",
  calendar: "M3 5h18v16H3zM3 10h18M8 3v4M16 3v4",
  meetings: "M4 6h16v10H8l-4 4zM8 10h8M8 13h5",
  truck: "M3 6h11v10H3zM14 9h4l3 3v4h-7M7 16a2 2 0 1 0 0 4a2 2 0 1 0 0-4M17 16a2 2 0 1 0 0 4a2 2 0 1 0 0-4",
  reports: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  stats: "M3 3v18h18M7 15l4-4 3 3 5-6",
  performance: "M12 2l3 6 6 .9-4.5 4.3 1 6.3L12 16.8 6.5 19.5l1-6.3L3 8.9 9 8z",
  pricing: "M3 12V4h8l10 10-8 8zM7.5 7a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3",
  settings: "M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1",
  search: "M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14M20 20l-3.5-3.5",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
  phone: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a1 1 0 0 1-1 1A16 16 0 0 1 4 5a1 1 0 0 1 1-1z",
  message: "M4 5h16v11H9l-5 4z",
  mail: "M3 5h18v14H3zM3 7l9 6 9-6",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  arrow: "M5 12h14M13 6l6 6-6 6",
  close: "M6 6l12 12M18 6L6 18",
  menu: "M4 6h16M4 12h16M4 18h16",
  collapse: "M15 6l-6 6 6 6",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  key: "M15 7a4 4 0 1 1-3.5 6L5 19.5V22H2v-3l6.5-6.5A4 4 0 0 1 15 7z",
  swap: "M7 7h13l-4-4M17 17H4l4 4",
  chevron: "M9 6l6 6-6 6",
  building: "M4 21V4h10v17M14 9h6v12M2 21h20M8 8h2M8 12h2M8 16h2M17 13h1M17 17h1",
  box: "M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10",
  terms: "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5",
  document: "M5 3h14v18H5zM8 7h8M8 11h8M8 15h5",
  shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6zM9 12l2 2 4-4",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
  user: "M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4 21c1-4 4-6 8-6s7 2 8 6",
  hardhat: "M3 17h18M5 17v-3a7 7 0 0 1 14 0v3M10 7V5h4v2",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6",
  history: "M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 8v4l3 2",
  rules: "M4 6h10M4 12h7M4 18h10M17 4v6M14 7h6M17 14v6",
  tracker: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 11.5v1",
  template: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
  block: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M5.6 5.6l12.8 12.8",
  video: "M3 6h12v12H3zM15 10l6-3v10l-6-3",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
  sun: "M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
};

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 18, strokeWidth = 2 }: { name: IconName; size?: number; strokeWidth?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name]} />
    </svg>
  );
}
