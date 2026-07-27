import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  ErrorHandler,
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
  apiBearerInterceptor,
  providePlatformApi,
  requestCorrelationInterceptor,
} from '@platform/api-client';

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
    { provide: API_REFRESH_STRATEGY, useExisting: AuthenticationService },
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
