import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { AppHeaderComponent } from '../../shared/navigation/app-header.component';
import { AppSidebarComponent } from '../../shared/navigation/app-sidebar.component';

@Component({
  imports: [RouterOutlet, AppHeaderComponent, AppSidebarComponent],
  template: `
    <div class="app-shell">
      <app-header [navigationOpen]="navigationOpen()" (navigationToggle)="toggleNavigation()" />
      <div class="shell-body">
        @if (!isCompact() || navigationOpen()) {
          <app-sidebar [compactOverlay]="isCompact()" (navigationSelected)="closeNavigation()" />
        }
        @if (isCompact() && navigationOpen()) {
          <button
            class="nav-scrim"
            type="button"
            aria-label="Close navigation"
            (click)="closeNavigation()"
          ></button>
        }
        <main id="main-content" class="shell-main" tabindex="-1">
          <router-outlet />
        </main>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuthenticatedLayoutComponent {
  private readonly breakpoints = inject(BreakpointObserver);
  private readonly router = inject(Router);

  readonly navigationOpen = signal(false);
  readonly isCompact = toSignal(
    this.breakpoints
      .observe([Breakpoints.Handset, Breakpoints.TabletPortrait])
      .pipe(map((result) => result.matches)),
    { initialValue: false },
  );

  constructor() {
    this.router.events
      .pipe(filter((event): event is NavigationEnd => event instanceof NavigationEnd))
      .subscribe(() => {
        this.navigationOpen.set(false);
      });
  }

  toggleNavigation(): void {
    this.navigationOpen.update((open) => !open);
  }

  closeNavigation(): void {
    this.navigationOpen.set(false);
  }
}
