import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

@Component({
  imports: [RouterLink, RouterOutlet],
  template: `
    <div class="public-shell">
      <header class="public-header">
        <a class="brand" routerLink="/login" aria-label="Website Generator sign in">
          <span class="brand-mark" aria-hidden="true">WG</span>
          <span>Website Generator</span>
        </a>
      </header>
      <main id="main-content" class="public-main" tabindex="-1">
        <router-outlet />
      </main>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PublicLayoutComponent {}
