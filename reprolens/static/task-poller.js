// One poll loop per visible issue. Late responses never cross route boundaries.
export function createTaskPoller({read, onState, onDone, onError, interval = 650}) {
  let generation = 0, timer = null;
  function stop() { generation++; clearTimeout(timer); timer = null; }
  function start(caseId, jobId) {
    stop();
    const current = generation;
    async function tick() {
      try {
        const job = await read(caseId, jobId);
        if (generation !== current) return;
        onState(job);
        if (!['queued', 'running'].includes(job.status)) {
          await onDone(job, () => generation === current);
          return;
        }
      } catch (error) {
        if (generation !== current) return;
        onError(error);
      }
      if (generation === current) timer = setTimeout(tick, interval);
    }
    tick();
  }
  return {start, stop};
}
