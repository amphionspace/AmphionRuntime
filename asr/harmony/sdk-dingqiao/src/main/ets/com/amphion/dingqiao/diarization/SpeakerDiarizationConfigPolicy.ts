export interface SpeakerDiarizationConfigValue {
  serviceUrl: string;
  serviceHeaders: Record<string, string>;
  maxSpeakers: number;
}

export interface ValidatedSpeakerDiarizationConfig {
  serviceUrl: string;
  serviceHeaders: Record<string, string>;
  maxSpeakers: number;
}

function isAllowedServiceUrl(value: string): boolean {
  if (/^https:\/\/[^\s/]+(?:\/[^\s]*)?$/i.test(value)) return true;
  return /^http:\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:\/[^\s]*)?$/i.test(value);
}

export function validateSpeakerDiarizationConfig(
  config: SpeakerDiarizationConfigValue): ValidatedSpeakerDiarizationConfig {
  if (!Number.isFinite(config.maxSpeakers) || !Number.isInteger(config.maxSpeakers) ||
    config.maxSpeakers < 1 || config.maxSpeakers > 4) {
    throw new Error('SpeakerDiarizationConfig.maxSpeakers must be an integer in [1, 4]');
  }
  const serviceUrl = config.serviceUrl.trim();
  if (!isAllowedServiceUrl(serviceUrl)) {
    throw new Error('SpeakerDiarizationConfig.serviceUrl must be HTTPS (loopback HTTP is allowed for development)');
  }
  const serviceHeaders: Record<string, string> = {};
  const sourceHeaders = config.serviceHeaders ?? {};
  const names = Object.keys(sourceHeaders);
  for (let index = 0; index < names.length; index++) {
    const name = names[index];
    const value = sourceHeaders[name];
    if (!/^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/.test(name) ||
      typeof value !== 'string' || /[\r\n]/.test(value)) {
      throw new Error(`SpeakerDiarizationConfig.serviceHeaders contains an invalid header: ${name}`);
    }
    serviceHeaders[name] = value;
  }
  return { serviceUrl, serviceHeaders, maxSpeakers: config.maxSpeakers };
}
