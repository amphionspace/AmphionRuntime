export function isValidRule3MinUtteranceSec(value: number): boolean {
  return value === -1 || (Number.isFinite(value) && value > 0);
}
