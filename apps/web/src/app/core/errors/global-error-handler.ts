import { ErrorHandler, Injectable, inject } from '@angular/core';

import { NotificationService } from '../notifications/notification.service';
import { toAppError } from './app-error';

@Injectable()
export class GlobalErrorHandler implements ErrorHandler {
  private readonly notifications = inject(NotificationService);

  handleError(error: unknown): void {
    const appError = toAppError(error);
    console.error('Unhandled application error', appError.cause ?? error);
    this.notifications.error(appError.message);
  }
}
