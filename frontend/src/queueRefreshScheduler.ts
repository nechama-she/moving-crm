// Coalesce live events while allowing only one refresh batch at a time.
export function createQueueRefreshScheduler(
  refresh: (firstContact: boolean, followups: boolean) => Promise<unknown>,
) {
  let queued = false;
  let running = false;
  let disposed = false;
  let firstContact = false;
  let followups = false;

  const schedule = () => {
    if (disposed || running || queued || (!firstContact && !followups)) return;
    queued = true;
    queueMicrotask(async () => {
      queued = false;
      if (disposed) return;
      running = true;
      const first = firstContact;
      const follow = followups;
      firstContact = false;
      followups = false;
      try {
        await refresh(first, follow);
      } finally {
        running = false;
        schedule();
      }
    });
  };

  return {
    request(first: boolean, follow: boolean) {
      firstContact ||= first;
      followups ||= follow;
      schedule();
    },
    dispose() {
      disposed = true;
    },
  };
}
