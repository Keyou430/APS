export type LocationLike = {
  pathname: string;
  hash: string;
};

export function normalizeLocation(location: LocationLike): string {
  if (location.pathname === "/" && location.hash === "#admin") {
    return "/admin";
  }
  return location.pathname;
}
