// Coalesce live events while allowing only one refresh batch at a time.
export function createQueueRefreshScheduler(
  refresh: (firstContact: boolean, followups: boolean) => Promise<unknown>,
  delay = 1000,
) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let running = false;
  let disposed = false;
  let firstContact = false;
  let followups = false;

  const schedule = () => {
    if (disposed || running || timer !== null || (!firstContact && !followups)) return;
    timer = setTimeout(async () => {
      timer = null;
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
    }, delay);
  };

  return {
    request(first: boolean, follow: boolean) {
      firstContact ||= first;
      followups ||= follow;
      schedule();
    },
    dispose() {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
    },
  };
}
