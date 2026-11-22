// The move page assistant: the page's steps it shows, and the conversation with BoxBot.

export type StepId = 'inventory' | 'services' | 'estimate' | 'bill_of_lading';
export type StepState = 'done' | 'current' | 'todo';

// One of the page's steps (1 Inventory, 2 Extra services, 3 Estimate, 4 Bill of Lading), as the page shows it.
export type AssistantStep = {
  id: StepId;
  label: string;
  state: StepState;
  // The page's own status text: "Completed", "Action required", "Changed - sign again"...
  status: string;
  // The step's button can be used now (it is not loading or waiting for the price).
  available: boolean;
  // What the step is waiting for, when it is: "Analyzing inventory...".
  busy?: string;
};

// What the window shows about the move and its company.
export type AssistantMove = {
  accessId: string;
  company: { name: string; phone: string; logo?: string };
  readOnly: boolean;
};

// The page's own screens the window can open from its buttons (the step strip, the upload button).
export type PageScreen = 'open_inventory' | 'open_services' | 'open_estimate' | 'open_bill_of_lading' | 'upload_files';

// What BoxBot can ask the page to open. It never signs: the customer signs in the page's own window.
export type BotAction = { type: 'open_signing'; signatureId: string } | { type: 'open_bol_signing' };

// Times for a video walkthrough. A tap sends "Book <start>".
export type SlotCard = {
  type: 'slots';
  days: { date: string; label: string; slots: { start: string; label: string }[] }[];
};

export type AssistantMessage = {
  id: string;
  role: 'assistant' | 'customer';
  text: string;
  cards?: SlotCard[];
  // A message that could not be answered (or the opening that failed): shown with a retry.
  failed?: { retry: { message: string } | { open: true } };
};

// BoxBot's answer, as the window uses it.
export type AssistantReply = {
  reply: string | null;
  quickReplies: string[];
  history?: AssistantMessage[];
  cards: SlotCard[];
  action?: BotAction;
  reverify: boolean;
};

export type Audience = 'customer' | 'rep';
