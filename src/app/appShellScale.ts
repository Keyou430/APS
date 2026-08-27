let appShellScaleRaf = 0
let appShellScaleInstalled = false

type AppShellViewport = {
  viewportWidth: number
  viewportHeight: number
  browserZoomFactor?: number
}

export function getAppShellScaleForViewport(_viewport: AppShellViewport) {
  return 1
}

export function getAppShellScale() {
  return 1
}

export function syncAppShellScale() {
  const shell = document.getElementById("appShell")
  const scale = getAppShellScale()
  const next = scale.toFixed(4)
  document.documentElement.style.setProperty("--app-shell-scale", next)
  if (shell) shell.dataset.scale = next
}

function scheduleAppShellScaleSync() {
  if (appShellScaleRaf) window.cancelAnimationFrame(appShellScaleRaf)
  appShellScaleRaf = window.requestAnimationFrame(() => {
    appShellScaleRaf = 0
    syncAppShellScale()
  })
}

export function installAppShellScale() {
  if (appShellScaleInstalled || typeof window === "undefined") return
  appShellScaleInstalled = true
  syncAppShellScale()
  window.addEventListener("resize", scheduleAppShellScaleSync, {
    passive: true,
  })
  window.visualViewport?.addEventListener("resize", scheduleAppShellScaleSync, {
    passive: true,
  })
}
