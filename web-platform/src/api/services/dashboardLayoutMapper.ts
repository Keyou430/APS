import type { DashboardLayouts } from "./dashboardService";

const RESPONSIVE_COLUMNS = {
  lg: 12,
  md: 8,
  sm: 4,
} as const;

const WIDGET_WIDTH = 4;
const WIDGET_HEIGHT = 2;

type LayoutBreakpoint = keyof typeof RESPONSIVE_COLUMNS;

function mapOrderToBreakpoint(
  order: string[],
  breakpoint: LayoutBreakpoint,
): DashboardLayouts[LayoutBreakpoint] {
  const columns = RESPONSIVE_COLUMNS[breakpoint];
  return order.map((id, index) => {
    const perRow = Math.max(1, Math.floor(columns / WIDGET_WIDTH));
    return {
      i: id,
      x: (index % perRow) * WIDGET_WIDTH,
      y: Math.floor(index / perRow) * WIDGET_HEIGHT,
      w: WIDGET_WIDTH,
      h: WIDGET_HEIGHT,
    };
  });
}

export function legacyCockpitOrderToDashboardLayouts(
  order: string[],
): DashboardLayouts {
  return {
    lg: mapOrderToBreakpoint(order, "lg"),
    md: mapOrderToBreakpoint(order, "md"),
    sm: mapOrderToBreakpoint(order, "sm"),
  };
}

export function dashboardLayoutsToCockpitOrder(
  layouts: DashboardLayouts,
  fallbackOrder: string[],
): string[] {
  const primaryLayout = Array.isArray(layouts.lg) ? layouts.lg : [];
  if (primaryLayout.length === 0) return fallbackOrder;

  const positioned = primaryLayout
    .filter((item) => item.i)
    .slice()
    .sort((left, right) => left.y - right.y || left.x - right.x)
    .map((item) => item.i);
  const missingFallbackItems = fallbackOrder.filter(
    (id) => !positioned.includes(id),
  );

  return [...positioned, ...missingFallbackItems];
}
