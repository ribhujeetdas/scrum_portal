export function createSprintState() {
  return {
    actionGeneration: 0,
    clientActionId: null,
    snapshotId: null,
    serverGeneration: null,
    responseRevision: 0,
    viewId: null,
    components: {},
    access: {},
    issues: new Map(),
    metrics: null,
    timer: null,
    controller: null,
    disposed: false,
    fetchedCoreRevision: null,
    fetchedComponents: new Map(),
    selection: null,
  };
}

export function beginAction(state, selection) {
  disposeAction(state);
  state.actionGeneration += 1;
  state.clientActionId = crypto.randomUUID();
  state.controller = new AbortController();
  state.selection = Object.freeze({ ...selection });
  state.disposed = false;
  return state.actionGeneration;
}

export function isCurrent(state, generation) {
  return !state.disposed && state.actionGeneration === generation;
}

export function disposeAction(state) {
  state.actionGeneration += 1;
  state.disposed = true;
  if (state.controller) state.controller.abort();
  if (state.timer) window.clearTimeout(state.timer);
  state.controller = null;
  state.timer = null;
  state.snapshotId = null;
  state.viewId = null;
  state.issues.clear();
  state.metrics = null;
  state.fetchedCoreRevision = null;
  state.fetchedComponents.clear();
}
