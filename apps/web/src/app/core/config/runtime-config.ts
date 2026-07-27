import { Injectable, signal } from '@angular/core';

import { environment } from '../../../environments/environment';

export interface RuntimeConfig {
  readonly apiBaseUrl: string;
  readonly previewBaseUrl: string;
  readonly supportUrl: string | null;
}

export type RuntimeConfigState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly config: RuntimeConfig }
  | { readonly status: 'error'; readonly message: string };

@Injectable({ providedIn: 'root' })
export class RuntimeConfigService {
  readonly state = signal<RuntimeConfigState>({ status: 'loading' });

  async load(): Promise<void> {
    try {
      const response = await fetch(environment.runtimeConfigUrl, {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`Runtime configuration returned HTTP ${String(response.status)}.`);
      }

      const config = parseRuntimeConfig(await response.json());
      this.state.set({ status: 'ready', config });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Runtime configuration is invalid.';
      this.state.set({ status: 'error', message });
      throw new Error(`Unable to load public runtime configuration: ${message}`, { cause: error });
    }
  }

  get config(): RuntimeConfig {
    const state = this.state();
    if (state.status !== 'ready') {
      throw new Error('Runtime configuration is not ready.');
    }
    return state.config;
  }
}

function parseRuntimeConfig(value: unknown): RuntimeConfig {
  if (!isRecord(value)) {
    throw new Error('Runtime configuration must be an object.');
  }

  return Object.freeze({
    apiBaseUrl: parseHttpUrl(value['apiBaseUrl'], 'apiBaseUrl'),
    previewBaseUrl: parseHttpUrl(value['previewBaseUrl'], 'previewBaseUrl'),
    supportUrl: parseOptionalHttpUrl(value['supportUrl'], 'supportUrl'),
  });
}

function parseHttpUrl(value: unknown, key: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${key} must be a non-empty URL.`);
  }
  const url = new URL(value);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(`${key} must use HTTP or HTTPS.`);
  }
  return url.toString().replace(/\/$/, '');
}

function parseOptionalHttpUrl(value: unknown, key: string): string | null {
  return value === null || value === undefined ? null : parseHttpUrl(value, key);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
