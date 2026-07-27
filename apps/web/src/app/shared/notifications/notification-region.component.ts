import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { NotificationService } from '../../core/notifications/notification.service';

@Component({
  selector: 'app-notification-region',
  template: `
    <section class="notification-region" aria-label="Notifications">
      @for (item of notifications.items(); track item.id) {
        <div class="notification" [attr.data-tone]="item.tone">
          <p>{{ item.message }}</p>
          <button
            class="notification-close"
            type="button"
            [attr.aria-label]="'Dismiss notification: ' + item.message"
            (click)="notifications.dismiss(item.id)"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NotificationRegionComponent {
  protected readonly notifications = inject(NotificationService);
}
