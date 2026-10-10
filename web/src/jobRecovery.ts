function delay(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => {clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError'));};
    const timer = window.setTimeout(() => {signal.removeEventListener('abort', abort); resolve();}, 1000);
    signal.addEventListener('abort', abort, {once: true});
    if (signal.aborted) abort();
  });
}

// Only waits for an already-running job; failed jobs are never retried here.
export async function postTeachingRequest(url: string, body: Record<string, unknown>, jobURL: string, signal: AbortSignal) {
  const post = () => fetch(url, {method: 'POST', signal, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const first = await post();
  if (first.status !== 409) return first;
  for (let poll = 0; poll < 180; poll++) {
    const response = await fetch(jobURL, {signal, cache: 'no-store'});
    if (!response.ok) break;
    const job = await response.json();
    if (job.status === 'generated') return post();
    if (job.status !== 'running') break;
    await delay(signal);
  }
  return first;
}
