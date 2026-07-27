import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthenticationService } from '../../core/auth/authentication.service';

@Component({
  selector: 'app-header',
  imports: [RouterLink],
  template: `
    <header class="app-header">
      <button
        class="icon-button nav-toggle"
        type="button"
        aria-controls="primary-navigation"
        aria-label="Toggle navigation"
        [attr.aria-expanded]="navigationOpen()"
        (click)="navigationToggle.emit()"
      >
        <span aria-hidden="true">☰</span>
      </button>
      <a class="brand" routerLink="/dashboard" aria-label="Website Generator dashboard">
        <span class="brand-mark" aria-hidden="true">WG</span>
        <span>Website Generator</span>
      </a>
      <div class="header-account">
        <span>{{ authentication.currentUser()?.email }}</span>
        <button class="secondary-button" type="button" (click)="logout()">Sign out</button>
      </div>
    </header>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppHeaderComponent {
  readonly authentication = inject(AuthenticationService);
  readonly navigationOpen = input.required<boolean>();
  readonly navigationToggle = output();

  logout(): void {
    void this.authentication.logout();
  }
}
