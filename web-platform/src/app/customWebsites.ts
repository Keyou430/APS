export type CustomWebsite = {
  id: string;
  name: string;
  url: string;
};

export type CustomWebsiteResult =
  | { ok: true; value: CustomWebsite }
  | { ok: false; error: "name_required" | "name_taken" | "url_invalid" };

function isCustomWebsiteId(value: string): boolean {
  return /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(value);
}

function normalizeWebsiteUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const candidate = /^[a-zA-Z][a-zA-Z\d+.-]*:/.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;

  try {
    const parsed = new URL(candidate);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

export function createCustomWebsite(
  current: CustomWebsite[],
  input: CustomWebsite,
): CustomWebsiteResult {
  const name = input.name.trim();
  if (!name) return { ok: false, error: "name_required" };

  const url = normalizeWebsiteUrl(input.url);
  if (!url) return { ok: false, error: "url_invalid" };

  const normalizedName = name.toLocaleLowerCase();
  const duplicate = current.some(
    (site) =>
      site.id !== input.id &&
      typeof site.name === "string" &&
      site.name.trim().toLocaleLowerCase() === normalizedName,
  );
  if (duplicate) return { ok: false, error: "name_taken" };

  return { ok: true, value: { id: input.id, name, url } };
}

export function parseCustomWebsites(value: unknown): CustomWebsite[] {
  if (!Array.isArray(value)) return [];

  const parsed: CustomWebsite[] = [];
  const ids = new Set<string>();
  for (const item of value) {
    if (!item || typeof item !== "object") continue;

    const candidate = item as Partial<CustomWebsite>;
    if (
      typeof candidate.id !== "string" ||
      !isCustomWebsiteId(candidate.id) ||
      typeof candidate.name !== "string" ||
      typeof candidate.url !== "string" ||
      ids.has(candidate.id)
    ) {
      continue;
    }

    const result = createCustomWebsite(parsed, {
      id: candidate.id,
      name: candidate.name,
      url: candidate.url,
    });
    if (!result.ok) continue;

    ids.add(result.value.id);
    parsed.push(result.value);
  }

  return parsed;
}
