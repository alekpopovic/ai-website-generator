import type { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { NotificationService } from '../notifications/notification.service';
import { toAppError } from './app-error';

export const httpErrorInterceptor: HttpInterceptorFn = (request, next) => {
  const notifications = inject(NotificationService);

  return next(request).pipe(
    catchError((error: unknown) => {
      const appError = toAppError(error);
      // Authentication screens render typed field and form errors themselves.
      // Avoid duplicate toasts, including the expected startup refresh rejection.
      if (!new URL(request.url, globalThis.location.origin).pathname.startsWith('/api/v1/auth/')) {
        notifications.error(appError.message);
      }
      return throwError(() => appError);
    }),
  );
};
