/**
 * Route definitions (ARCHITECTURE app/routes/: "route definitions only").
 *
 * The router and the feature routes (findings, reconciliation, connectors,
 * dashboard) are wired in Slice 4. Slice 0 declares the typed shape so the home
 * exists and feature slices have a contract to register against.
 */

export interface RouteDef {
  readonly path: string;
  readonly label: string;
}

export const routes: readonly RouteDef[] = [];
