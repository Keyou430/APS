type LegacyWorkspaceHostProps = {
  routeId: string;
};

export function LegacyWorkspaceHost({ routeId }: LegacyWorkspaceHostProps) {
  return (
    <div
      aria-label="legacy workspace host"
      data-route={routeId}
      id="legacyWorkspaceHost"
    />
  );
}
