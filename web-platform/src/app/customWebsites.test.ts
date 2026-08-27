import { describe, expect, it } from "vitest";
import {
  createCustomWebsite,
  parseCustomWebsites,
} from "./customWebsites";

describe("createCustomWebsite", () => {
  it("normalizes a protocol-less URL and trims the name", () => {
    expect(
      createCustomWebsite([], {
        id: "site-a",
        name: "  采购门户  ",
        url: "procurement.example.com",
      }),
    ).toEqual({
      ok: true,
      value: {
        id: "site-a",
        name: "采购门户",
        url: "https://procurement.example.com/",
      },
    });
  });

  it("rejects blank names", () => {
    expect(
      createCustomWebsite([], {
        id: "site-a",
        name: "   ",
        url: "https://procurement.example.com",
      }),
    ).toEqual({ ok: false, error: "name_required" });
  });

  it("rejects duplicate names except when editing the same record", () => {
    const sites = [
      { id: "site-a", name: "采购门户", url: "https://example.com/" },
    ];

    expect(
      createCustomWebsite(sites, {
        id: "site-b",
        name: "采购门户",
        url: "https://other.example",
      }),
    ).toEqual({ ok: false, error: "name_taken" });

    expect(
      createCustomWebsite(sites, {
        id: "site-a",
        name: "采购门户",
        url: "https://other.example",
      }),
    ).toMatchObject({ ok: true });
  });

  it("rejects URLs outside HTTP and HTTPS", () => {
    expect(
      createCustomWebsite([], {
        id: "site-a",
        name: "本地文件",
        url: "file:///C:/private.html",
      }),
    ).toEqual({ ok: false, error: "url_invalid" });
  });
});

describe("parseCustomWebsites", () => {
  it("keeps only valid normalized records from persisted data", () => {
    expect(
      parseCustomWebsites([
        { id: "site-a", name: "采购门户", url: "procurement.example.com" },
        { id: "site-b", name: "", url: "https://blank-name.example" },
        { id: "site-c", name: "本地文件", url: "file:///C:/private.html" },
        { id: "site-d", name: "采购门户", url: "https://duplicate.example" },
        { name: "缺少标识", url: "https://missing-id.example" },
      ]),
    ).toEqual([
      {
        id: "site-a",
        name: "采购门户",
        url: "https://procurement.example.com/",
      },
    ]);
  });

  it("falls back to an empty list for malformed storage values", () => {
    expect(parseCustomWebsites("not an array")).toEqual([]);
  });

  it("drops records with unsafe identifiers", () => {
    expect(
      parseCustomWebsites([
        { id: 'site" onclick="alert(1)', name: "不安全", url: "https://unsafe.example" },
      ]),
    ).toEqual([]);
  });
});
