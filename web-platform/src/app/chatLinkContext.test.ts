import { describe, expect, it } from "vitest";
import { normalizeChatLink } from "./chatLinkContext";

describe("normalizeChatLink", () => {
  it("preserves an HTTPS collaboration URL", () => {
    expect(
      normalizeChatLink(
        "https://my.feishu.cn/base/appToken?table=tblToken&view=viewToken",
      ),
    ).toBe(
      "https://my.feishu.cn/base/appToken?table=tblToken&view=viewToken",
    );
  });

  it.each(["", "link_1720000000000", "javascript:alert(1)", "file:///tmp/a"])(
    "rejects non-HTTP link context %s",
    (value) => {
      expect(normalizeChatLink(value)).toBe("");
    },
  );
});
