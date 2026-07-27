import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { environment } from '../../../environments/environment';

interface NavigationItem {
  readonly label: string;
  readonly path: string;
  readonly symbol: string;
}

@Component({
  selector: 'app-sidebar',
  imports: [RouterLink, RouterLinkActive],
  template: `
    <aside
      id="primary-navigation"
      class="sidebar"
      [class.sidebar-overlay]="compactOverlay()"
      aria-label="Primary navigation"
    >
      <nav>
        <ul class="nav-list">
          @for (item of primaryItems; track item.path) {
            <li>
              <a
                class="nav-link"
                [routerLink]="item.path"
                routerLinkActive="nav-link-active"
                [routerLinkActiveOptions]="{ exact: true }"
                (click)="navigationSelected.emit()"
              >
                <span class="nav-symbol" aria-hidden="true">{{ item.symbol }}</span>
                <span>{{ item.label }}</span>
              </a>
            </li>
          }
        </ul>
      </nav>
      <nav class="sidebar-secondary" aria-label="Workspace navigation">
        <a
          class="nav-link"
          routerLink="/settings"
          routerLinkActive="nav-link-active"
          (click)="navigationSelected.emit()"
        >
          <span class="nav-symbol" aria-hidden="true">S</span>
          <span>Settings</span>
        </a>
      </nav>
    </aside>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppSidebarComponent {
  readonly compactOverlay = input(false);
  readonly navigationSelected = output();

  readonly primaryItems: readonly NavigationItem[] = [
    { label: 'Dashboard', path: '/dashboard', symbol: 'D' },
    { label: 'Projects', path: '/projects', symbol: 'P' },
    { label: 'Scanner', path: '/scanner', symbol: 'S' },
    { label: 'Datasets', path: '/datasets', symbol: 'D' },
    { label: 'Models', path: '/models', symbol: 'M' },
    { label: 'Generator', path: '/generator', symbol: 'G' },
    ...(!environment.production
      ? [{ label: 'Diagnostics', path: '/diagnostics', symbol: '!' }]
      : []),
  ];
}
