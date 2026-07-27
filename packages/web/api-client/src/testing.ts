import type { HttpInterceptorFn } from '@angular/common/http';
import { HttpResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { makeEnvironmentProviders } from '@angular/core';
import { of } from 'rxjs';

import type { ApiResponseVersionInfo, DependencyHealthResponse } from './generated/types.gen';

export interface FakePlatformApiFixtures {
  readonly dependencyHealth: DependencyHealthResponse;
  readonly version: ApiResponseVersionInfo;
}

export function provideFakePlatformApiForTesting(fixtures: FakePlatformApiFixtures) {
  const interceptor: HttpInterceptorFn = (request, next) => {
    const path = new URL(request.url).pathname;
    if (path === '/api/v1/version')
      return of(new HttpResponse({ body: fixtures.version, status: 200 }));
    if (path === '/health/dependencies')
      return of(new HttpResponse({ body: fixtures.dependencyHealth, status: 200 }));
    return next(request);
  };
  return makeEnvironmentProviders([provideHttpClient(withInterceptors([interceptor]))]);
}
