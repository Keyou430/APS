export function isCockpitDecisionDemoMode(env = import.meta.env) {
  return env?.VITE_USE_MOCK === "true"
}
