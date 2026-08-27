export type UiState = {
  activeView: string;
  sidebarWidth: number;
};

export type UiStore = {
  getState(): UiState;
  setActiveView(activeView: string): void;
  setSidebarWidth(sidebarWidth: number): void;
  subscribe(listener: (state: UiState) => void): () => void;
};

const defaultUiState: UiState = {
  activeView: "workspace",
  sidebarWidth: 280,
};

export function createUiStore(initialState: Partial<UiState> = {}): UiStore {
  let state = { ...defaultUiState, ...initialState };
  const listeners = new Set<(state: UiState) => void>();

  function emit() {
    listeners.forEach((listener) => listener(state));
  }

  function update(nextState: Partial<UiState>) {
    state = { ...state, ...nextState };
    emit();
  }

  return {
    getState() {
      return state;
    },
    setActiveView(activeView) {
      update({ activeView });
    },
    setSidebarWidth(sidebarWidth) {
      update({ sidebarWidth });
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
