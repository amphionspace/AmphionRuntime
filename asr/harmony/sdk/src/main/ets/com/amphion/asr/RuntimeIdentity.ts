export const HARMONY_SDK_VERSION: string = '0.2.9';
export const HARMONY_SDK_MAJOR: number = 1;
export const HARMONY_SDK_RELEASE_DATE: string = '2026-07-30';

export class LicenseIdentityFailure {
  static readonly NONE: string = 'NONE';
  static readonly SDK_MAJOR_MISMATCH: string = 'SDK_MAJOR_MISMATCH';
  static readonly MAINTENANCE_EXPIRED: string = 'MAINTENANCE_EXPIRED';
}

export function evaluateLicenseIdentity(claimSdkMajor: number, runtimeSdkMajor: number,
  maintenanceUntil: string, runtimeReleaseDate: string): string {
  if (claimSdkMajor > 0 && runtimeSdkMajor > 0 && claimSdkMajor !== runtimeSdkMajor) {
    return LicenseIdentityFailure.SDK_MAJOR_MISMATCH;
  }
  if (runtimeReleaseDate.length > 0 && maintenanceUntil.length > 0 &&
    runtimeReleaseDate > maintenanceUntil) {
    return LicenseIdentityFailure.MAINTENANCE_EXPIRED;
  }
  return LicenseIdentityFailure.NONE;
}
