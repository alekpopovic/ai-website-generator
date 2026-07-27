import type { HttpInterceptorFn } from '@angular/common/http';
import { HttpContextToken, HttpErrorResponse } from '@angular/common/http';
import { Injectable, InjectionToken, inject, signal } from '@angular/core';
import {
  Observable,
  catchError,
  finalize,
  of,
  shareReplay,
  switchMap,
  tap,
  throwError,
} from 'rxjs';

import { PlatformApiConfiguration } from './configuration';

export interface ApiRefreshStrategy {
  refreshAccessToken(): Observable<string | null>;
  clearSession(): void;
}

const NO_REFRESH_STRATEGY: ApiRefreshStrategy = {
  refreshAccessToken: () => of(null),
  clearSession: () => undefined,
};

export const API_REFRESH_STRATEGY = new InjectionToken<ApiRefreshStrategy>('API_REFRESH_STRATEGY', {
  providedIn: 'root',
  factory: () => NO_REFRESH_STRATEGY,
});

export const SKIP_API_AUTH = new HttpContextToken<boolean>(() => false);
const ACCESS_TOKEN_REFRESHED = new HttpContextToken<boolean>(() => false);

@Injectable({ providedIn: 'root' })
export class ApiAccessTokenStore {
  private readonly value = signal<string | null>(null);
  readonly accessToken = this.value.asReadonly();

  set(accessToken: string | null): void {
    this.value.set(accessToken);
  }

  clear(): void {
    this.value.set(null);
  }
}

@Injectable({ providedIn: 'root' })
export class ApiRefreshCoordinator {
  private readonly strategy = inject(API_REFRESH_STRATEGY);
  private readonly tokens = inject(ApiAccessTokenStore);
  private inFlight: Observable<string | null> | null = null;

  refresh(): Observable<string | null> {
    this.inFlight ??= this.strategy.refreshAccessToken().pipe(
      tap((token) => {
        this.tokens.set(token);
      }),
      catchError((error: unknown) => {
        this.tokens.clear();
        this.strategy.clearSession();
        return throwError(() => error);
      }),
      finalize(() => {
        this.inFlight = null;
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    return this.inFlight;
  }
}

export const apiBearerInterceptor: HttpInterceptorFn = (request, next) => {
  const configuration = inject(PlatformApiConfiguration);
  const tokens = inject(ApiAccessTokenStore);
  const refresh = inject(ApiRefreshCoordinator);

  if (!configuration.isApiUrl(request.url) || request.context.get(SKIP_API_AUTH)) {
    return next(request);
  }

  const authorized = withBearer(request, tokens.accessToken());
  return next(authorized).pipe(
    catchError((error: unknown) => {
      if (
        !(error instanceof HttpErrorResponse) ||
        error.status !== 401 ||
        request.context.get(ACCESS_TOKEN_REFRESHED)
      ) {
        return throwError(() => error);
      }
      return refresh.refresh().pipe(
        switchMap((accessToken) => {
          if (accessToken === null) return throwError(() => error);
          const retried = withBearer(
            request.clone({ context: request.context.set(ACCESS_TOKEN_REFRESHED, true) }),
            accessToken,
          );
          return next(retried);
        }),
      );
    }),
  );
};

function withBearer<T>(
  request: import('@angular/common/http').HttpRequest<T>,
  token: string | null,
) {
  return token === null
    ? request
    : request.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}
