import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  ErrorHandler,
  Injector,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
} from '@angular/core';
import type { ApplicationConfig } from '@angular/core';
import { TitleStrategy, provideRouter, withComponentInputBinding } from '@angular/router';
import {
  API_REFRESH_STRATEGY,
  PlatformApiConfiguration,
  type ApiRefreshStrategy,
  apiBearerInterceptor,
  providePlatformApi,
  requestCorrelationInterceptor,
} from '@platform/api-client';
import { defer } from 'rxjs';

import { AuthenticationService } from './core/auth/authentication.service';
import { RuntimeConfigService } from './core/config/runtime-config';
import { GlobalErrorHandler } from './core/errors/global-error-handler';
import { httpErrorInterceptor } from './core/errors/http-error.interceptor';
import { AppTitleStrategy } from './core/routing/app-title.strategy';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(
      withInterceptors([requestCorrelationInterceptor, httpErrorInterceptor, apiBearerInterceptor]),
    ),
    providePlatformApi(),
    {
      provide: API_REFRESH_STRATEGY,
      useFactory: (): ApiRefreshStrategy => {
        const injector = inject(Injector);
        return {
          refreshAccessToken: () =>
            defer(() => injector.get(AuthenticationService).refreshAccessToken()),
          clearSession: () => {
            injector.get(AuthenticationService).clearSession();
          },
        };
      },
    },
    provideAppInitializer(() => {
      const runtime = inject(RuntimeConfigService);
      const api = inject(PlatformApiConfiguration);
      const authentication = inject(AuthenticationService);
      return runtime.load().then(async () => {
        api.configure({ baseUrl: runtime.config.apiBaseUrl });
        await authentication.initialize();
      });
    }),
    { provide: TitleStrategy, useClass: AppTitleStrategy },
    { provide: ErrorHandler, useClass: GlobalErrorHandler },
  ],
};
