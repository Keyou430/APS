import { describe, expect, it } from "vitest"

import { getAppShellScaleForViewport } from "./appShellScale"

describe("app shell scale", () => {
  it("keeps the native shell scale for a narrower viewport", () => {
    expect(
      getAppShellScaleForViewport({
        viewportWidth: 1280,
        viewportHeight: 900,
        browserZoomFactor: 1,
      }),
    ).toBe(1)
  })

  it("lets the browser own font scaling at 110%", () => {
    expect(
      getAppShellScaleForViewport({
        viewportWidth: 1440 / 1.1,
        viewportHeight: 900 / 1.1,
        browserZoomFactor: 1.1,
      }),
    ).toBe(1)
  })
})
