/** Pure package-policy evaluator shared by the HarmonyOS ASR license paths. */
export function applicationMatches(
  mode: string,
  licensedBundle: string,
  bundleNames: string[],
  runtimeBundle: string
): boolean {
  const normalizedMode = mode.trim().toLowerCase();
  if (normalizedMode.length === 0 || normalizedMode === 'none' || normalizedMode === 'record-only') {
    return true;
  }
  if (normalizedMode === 'bound') {
    return licensedBundle.length > 0 && licensedBundle === runtimeBundle;
  }
  if (normalizedMode === 'allowlist') {
    return bundleNames.length > 0 && bundleNames.includes(runtimeBundle);
  }
  return false;
}
