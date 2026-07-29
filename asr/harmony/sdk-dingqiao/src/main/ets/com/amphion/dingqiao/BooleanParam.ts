export function strictBooleanParam(
  params: Record<string, Object>,
  key: string,
  defaultValue: boolean
): boolean {
  const value = params[key];
  return typeof value === 'boolean' ? value : defaultValue;
}

export function compatibleBooleanParam(
  params: Record<string, Object>,
  key: string,
  defaultValue: boolean
): boolean {
  const value = params[key];
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? value !== 0 : defaultValue;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    return normalized === 'true' || normalized === '1';
  }
  return defaultValue;
}
