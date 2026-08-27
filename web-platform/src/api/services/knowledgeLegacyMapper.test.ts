import { describe, expect, it } from "vitest";
import { mapKnowledgeEntriesToLegacyCards } from "./knowledgeLegacyMapper";

describe("knowledge legacy mapper", () => {
  it("maps contract knowledge entries to legacy knowledge card fields", () => {
    const cards = mapKnowledgeEntriesToLegacyCards({
      items: [
        {
          id: 12,
          title: "平台契约说明",
          type: "file",
          status: "ready",
          collection_id: 4,
          visibility: "organization",
        },
      ],
    });

    expect(cards).toEqual([
      {
        display_name: "平台契约说明",
        enabled: true,
        id: "12",
        is_default_import_target: false,
        resource_id: "knowledge-12",
        resource_type: "file",
        stale: false,
        title: "平台契约说明",
      },
    ]);
  });

  it("marks archived or disabled entries as disabled cards", () => {
    const cards = mapKnowledgeEntriesToLegacyCards({
      items: [
        { id: "archived", title: "归档", status: "archived" },
        { id: "disabled", title: "停用", enabled: false },
      ],
    });

    expect(cards.map((card) => card.enabled)).toEqual([false, false]);
  });

  it("preserves the real URL for draggable link entries", () => {
    const cards = mapKnowledgeEntriesToLegacyCards({
      items: [
        {
          id: 18,
          title: "飞书多维表格",
          type: "link",
          url: "https://my.feishu.cn/base/appToken?table=tblToken",
          status: "ready",
        },
      ],
    });

    expect(cards[0]).toMatchObject({
      id: "18",
      resource_type: "link",
      link_url: "https://my.feishu.cn/base/appToken?table=tblToken",
    });
  });
});
