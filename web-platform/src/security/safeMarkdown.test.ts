import { describe, expect, it } from "vitest";
import { renderSafeAssistantMarkdown } from "./safeMarkdown";

describe("safe assistant markdown renderer", () => {
  it("escapes raw html and removes dangerous link protocols", () => {
    const html = renderSafeAssistantMarkdown(
      '<img src=x onerror=alert(1)> [open](javascript:alert(1))',
    );

    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("javascript:");
    expect(html).toContain("<a");
    expect(html).toContain('rel="noreferrer noopener"');
  });

  it("renders block markdown without leaking raw syntax", () => {
    const html = renderSafeAssistantMarkdown(
      "# Heading\n\n- first\n- second\n\n**bold** and `const answer = 42`\n\n```ts\nconst safe = true\n```",
    );

    expect(html).toContain("<h1>Heading</h1>");
    expect(html).toContain("<ul><li>first</li><li>second</li></ul>");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<code>const answer = 42</code>");
    expect(html).toContain('<pre><code class="language-ts">const safe = true</code></pre>');
    expect(html).not.toContain("**bold**");
  });
});
