import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  imports: [RouterLink],
  template: `
    <main id="main-content" class="not-found" tabindex="-1">
      <p class="eyebrow">404</p>
      <h1>Page not found</h1>
      <p>The page may have moved or the address may be incorrect.</p>
      <a class="primary-button" routerLink="/dashboard">Return to dashboard</a>
    </main>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NotFoundPageComponent {}
