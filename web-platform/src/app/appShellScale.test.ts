import { describe, expect, it } from "vitest"

import { getAppShellScaleForViewport } from "./appShellScale"

describe("app shell scale", () => {
  it("keeps the shell at native scale for responsive layouts", () => {
    expect(
      getAppShellScaleForViewport({
        viewportWidth: 390,
        viewportHeight: 844,
        browserZoomFactor: 1,
      }),
    ).toBe(1)
  })

  it("does not cancel browser zoom when the viewport shrinks at 110%", () => {
    const scale = getAppShellScaleForViewport({
      viewportWidth: 1440 / 1.1,
      viewportHeight: 900 / 1.1,
      browserZoomFactor: 1.1,
    })

    expect(scale).toBe(1)
  })
})
