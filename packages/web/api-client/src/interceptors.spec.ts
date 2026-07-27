import { HttpErrorResponse, HttpRequest, HttpResponse } from '@angular/common/http';
import { Injector, runInInjectionContext } from '@angular/core';
import { firstValueFrom, of, throwError } from 'rxjs';

import {
  API_REFRESH_STRATEGY,
  ApiAccessTokenStore,
  ApiRefreshCoordinator,
  apiBearerInterceptor,
} from './auth';
import { PlatformApiConfiguration } from './configuration';
import { REQUEST_ID_FACTORY, requestCorrelationInterceptor } from './correlation';

describe('API transport interceptors', () => {
  it('adds a deterministic correlation ID only to API-origin requests', async () => {
    const configuration = new PlatformApiConfiguration();
    configuration.configure({ baseUrl: 'https://api.example.test' });
    const injector = Injector.create({
      providers: [
        { provide: PlatformApiConfiguration, useValue: configuration },
        { provide: REQUEST_ID_FACTORY, useValue: () => 'request-test' },
      ],
    });
    const requestIds: (string | null)[] = [];

    await firstValueFrom(
      runInInjectionContext(injector, () =>
        requestCorrelationInterceptor(
          new HttpRequest('GET', 'https://api.example.test/api/v1/version'),
          (request) => {
            requestIds.push(request.headers.get('X-Request-ID'));
            return of(new HttpResponse({ status: 200 }));
          },
        ),
      ),
    );

    expect(requestIds).toEqual(['request-test']);
    injector.destroy();
  });

  it('refreshes once after a 401 and retries with the new bearer token', async () => {
    const configuration = new PlatformApiConfiguration();
    configuration.configure({ baseUrl: 'https://api.example.test' });
    const tokens = new ApiAccessTokenStore();
    tokens.set('expired-token');
    const refreshStrategy = {
      refreshAccessToken: () => of('fresh-token'),
      clearSession: vi.fn(),
    };
    const injector = Injector.create({
      providers: [
        { provide: PlatformApiConfiguration, useValue: configuration },
        { provide: ApiAccessTokenStore, useValue: tokens },
        { provide: API_REFRESH_STRATEGY, useValue: refreshStrategy },
        ApiRefreshCoordinator,
      ],
    });
    const authorizationHeaders: (string | null)[] = [];

    await firstValueFrom(
      runInInjectionContext(injector, () =>
        apiBearerInterceptor(
          new HttpRequest('GET', 'https://api.example.test/api/v1/version'),
          (request) => {
            authorizationHeaders.push(request.headers.get('Authorization'));
            return authorizationHeaders.length === 1
              ? throwError(() => new HttpErrorResponse({ status: 401 }))
              : of(new HttpResponse({ status: 200 }));
          },
        ),
      ),
    );

    expect(authorizationHeaders).toEqual(['Bearer expired-token', 'Bearer fresh-token']);
    expect(refreshStrategy.clearSession).not.toHaveBeenCalled();
    injector.destroy();
  });

  it('never attaches bearer tokens to or recursively refreshes public auth requests', async () => {
    const configuration = new PlatformApiConfiguration();
    configuration.configure({ baseUrl: 'https://api.example.test' });
    const tokens = new ApiAccessTokenStore();
    tokens.set('private-access-token');
    const refreshStrategy = {
      refreshAccessToken: vi.fn(() => of('unexpected-token')),
      clearSession: vi.fn(),
    };
    const injector = Injector.create({
      providers: [
        { provide: PlatformApiConfiguration, useValue: configuration },
        { provide: ApiAccessTokenStore, useValue: tokens },
        { provide: API_REFRESH_STRATEGY, useValue: refreshStrategy },
        ApiRefreshCoordinator,
      ],
    });
    let authorization: string | null = null;

    await expect(
      firstValueFrom(
        runInInjectionContext(injector, () =>
          apiBearerInterceptor(
            new HttpRequest('POST', 'https://api.example.test/api/v1/auth/refresh', null),
            (request) => {
              authorization = request.headers.get('Authorization');
              return throwError(() => new HttpErrorResponse({ status: 401 }));
            },
          ),
        ),
      ),
    ).rejects.toBeInstanceOf(HttpErrorResponse);

    expect(authorization).toBeNull();
    expect(refreshStrategy.refreshAccessToken).not.toHaveBeenCalled();
    injector.destroy();
  });
});
