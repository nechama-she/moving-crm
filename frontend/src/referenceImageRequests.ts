export type ReferenceImage = { url: string; room: string; name: string; expires_at: number };
type Task = { name: string; resolve: (rows: ReferenceImage[]) => void; reject: (error: Error) => void };
type Group = { endpoint: string; linkKey: string; session: string; tasks: Task[]; running: boolean };
const groups = new Map<string, Group>();
const pending = new Map<string, Promise<ReferenceImage[]>>();

async function drain(key: string, group: Group) {
  if (group.running) return;
  group.running = true;
  try {
    while (group.tasks.length) {
      const tasks = group.tasks.splice(0, 60000);
      try {
        const response = await fetch(group.endpoint, { method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-public-link': group.linkKey, 'x-public-session': group.session },
          body: JSON.stringify({ names: tasks.map(task => task.name) }) });
        if (!response.ok) throw new Error(response.status === 429
          ? 'Photo requests were rate-limited. Please reopen the inventory shortly.'
          : 'Reference photos could not be loaded.');
        const body = await response.json();
        for (const task of tasks) task.resolve(body.images?.[task.name] || []);
      } catch (error) {
        for (const task of tasks) task.reject(error instanceof Error ? error : new Error('Reference photos could not be loaded.'));
      }
    }
  } finally {
    groups.delete(key);
  }
}

export function requestReferenceImages(endpoint: string, linkKey: string, session: string, name: string): Promise<ReferenceImage[]> {
  const key = JSON.stringify([endpoint, linkKey, session]);
  const itemKey = JSON.stringify([key, name]);
  const existing = pending.get(itemKey);
  if (existing) return existing;
  let group = groups.get(key);
  if (!group) {
    group = { endpoint, linkKey, session, tasks: [], running: false };
    groups.set(key, group);
    const scheduled = group;
    setTimeout(() => { void drain(key, scheduled); }, 0);
  }
  const promise = new Promise<ReferenceImage[]>((resolve, reject) => group!.tasks.push({ name, resolve, reject }));
  pending.set(itemKey, promise);
  void promise.finally(() => pending.delete(itemKey)).catch(() => {});
  return promise;
}
