import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { NotificationRegionComponent } from './shared/notifications/notification-region.component';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, NotificationRegionComponent],
  template: `
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <router-outlet />
    <app-notification-region />
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {}
