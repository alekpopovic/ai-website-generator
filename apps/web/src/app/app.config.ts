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
  PlatformApiConfiguration,
  apiBearerInterceptor,
  providePlatformApi,
  requestCorrelationInterceptor,
} from '@platform/api-client';

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
    provideAppInitializer(() => {
      const runtime = inject(RuntimeConfigService);
      const api = inject(PlatformApiConfiguration);
      return runtime.load().then(() => {
        api.configure({ baseUrl: runtime.config.apiBaseUrl });
      });
    }),
    { provide: TitleStrategy, useClass: AppTitleStrategy },
    { provide: ErrorHandler, useClass: GlobalErrorHandler },
  ],
};
