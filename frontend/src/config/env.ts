/**
 * Typed, public-only frontend env access (§16).
 *
 * Only `VITE_`-prefixed variables ever reach the bundle — that is a Vite guarantee
 * and a hard rule here: no secret or server-side value is read in this module. This
 * is the single place the app reads `import.meta.env`, so the public surface is
 * auditable in one file.
 */

interface PublicEnv {
  /** Base URL of the Yieldfield API (the `/api/v1` surface lives under this). */
  readonly apiBaseUrl: string;
  /** Deploy environment label, for display/telemetry only. */
  readonly environment: string;
}

export const env: PublicEnv = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  environment: import.meta.env.VITE_ENVIRONMENT ?? 'local',
};
