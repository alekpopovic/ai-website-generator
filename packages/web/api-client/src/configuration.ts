import { Injectable, makeEnvironmentProviders } from '@angular/core';

import { client } from './generated/client.gen';
import { provideHeyApiClient } from './generated/client/client.gen';

export interface PlatformApiConfigurationValue {
  readonly baseUrl: string;
  readonly withCredentials?: boolean;
}

@Injectable({ providedIn: 'root' })
export class PlatformApiConfiguration {
  private currentBaseUrl: string | null = null;

  configure(value: PlatformApiConfigurationValue): void {
    this.currentBaseUrl = normalizeBaseUrl(value.baseUrl);
    client.setConfig({
      baseUrl: this.currentBaseUrl,
      credentials: value.withCredentials === false ? 'same-origin' : 'include',
    });
  }

  isApiUrl(url: string): boolean {
    return (
      this.currentBaseUrl !== null &&
      (url === this.currentBaseUrl || url.startsWith(`${this.currentBaseUrl}/`))
    );
  }

  isApiPath(url: string, path: string): boolean {
    if (!this.isApiUrl(url) || this.currentBaseUrl === null) return false;
    return new URL(url).pathname === path;
  }

  buildSseUrl(
    path: `/${string}`,
    query: Readonly<Record<string, string | number | boolean>> = {},
  ): string {
    if (this.currentBaseUrl === null) {
      throw new Error('Platform API configuration is not ready.');
    }
    if (path.startsWith('//') || path.includes('://')) {
      throw new Error('SSE paths must be relative to the configured API origin.');
    }
    const url = new URL(`${this.currentBaseUrl}${path}`);
    for (const [key, value] of Object.entries(query)) url.searchParams.set(key, String(value));
    return url.toString();
  }

  buildUrl(
    path: `/${string}`,
    query: Readonly<Record<string, string | number | boolean | null | undefined>> = {},
  ): string {
    if (this.currentBaseUrl === null) {
      throw new Error('Platform API configuration is not ready.');
    }
    if (path.startsWith('//') || path.includes('://')) {
      throw new Error('API paths must be relative to the configured API origin.');
    }
    const url = new URL(`${this.currentBaseUrl}${path}`);
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
    }
    return url.toString();
  }
}

export function providePlatformApi() {
  return makeEnvironmentProviders([provideHeyApiClient(client)]);
}

function normalizeBaseUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('The API base URL must use HTTP or HTTPS.');
  }
  return url.toString().replace(/\/$/, '');
}
