import type { HttpInterceptorFn } from '@angular/common/http';
import { InjectionToken, inject } from '@angular/core';

import { PlatformApiConfiguration } from './configuration';

export type RequestIdFactory = () => string;

export const REQUEST_ID_FACTORY = new InjectionToken<RequestIdFactory>('REQUEST_ID_FACTORY', {
  providedIn: 'root',
  factory: () => () => globalThis.crypto.randomUUID(),
});

export const requestCorrelationInterceptor: HttpInterceptorFn = (request, next) => {
  const configuration = inject(PlatformApiConfiguration);
  if (!configuration.isApiUrl(request.url) || request.headers.has('X-Request-ID')) {
    return next(request);
  }
  const requestId = inject(REQUEST_ID_FACTORY)();
  return next(request.clone({ setHeaders: { 'X-Request-ID': requestId } }));
};
