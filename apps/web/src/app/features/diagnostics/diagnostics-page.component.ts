import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Health, System } from '@platform/api-client';
import type { DependencyHealthResponse, VersionInfo } from '@platform/api-client';

import { LoadingStateComponent } from '../../shared/states/loading-state.component';

type DiagnosticsState =
  | { readonly status: 'loading' }
  | {
      readonly status: 'ready';
      readonly dependencies: DependencyHealthResponse;
      readonly version: VersionInfo;
    }
  | { readonly status: 'error'; readonly message: string };

@Component({
  imports: [LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="diagnostics-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Development only</p>
          <h1 id="diagnostics-heading">API diagnostics</h1>
          <p>Generated-client connectivity and control-plane dependency readiness.</p>
        </div>
        <button class="secondary-button" type="button" (click)="reload()">Refresh</button>
      </header>

      @switch (state().status) {
        @case ('loading') {
          <app-loading-state label="Checking the control plane…" />
        }
        @case ('error') {
          <div class="state-card" role="alert">
            <div>
              <h2>Diagnostics unavailable</h2>
              <p>{{ errorMessage }}</p>
            </div>
          </div>
        }
        @case ('ready') {
          <div class="diagnostic-grid">
            <section class="diagnostic-card" aria-labelledby="api-version-heading">
              <h2 id="api-version-heading">API version</h2>
              <dl>
                <div>
                  <dt>Contract</dt>
                  <dd>{{ readyState?.version?.api_version }}</dd>
                </div>
                <div>
                  <dt>Service</dt>
                  <dd>{{ readyState?.version?.service_version }}</dd>
                </div>
                <div>
                  <dt>Environment</dt>
                  <dd>{{ readyState?.version?.environment }}</dd>
                </div>
              </dl>
            </section>
            <section class="diagnostic-card" aria-labelledby="dependency-heading">
              <h2 id="dependency-heading">Dependency readiness</h2>
              <p class="status-pill" [attr.data-state]="readyState?.dependencies?.status">
                {{ readyState?.dependencies?.status }}
              </p>
              <ul class="dependency-list">
                @for (
                  dependency of readyState?.dependencies?.dependencies ?? [];
                  track dependency.name
                ) {
                  <li>
                    <span>{{ dependency.name }}</span>
                    <strong [attr.data-state]="dependency.state">{{ dependency.state }}</strong>
                  </li>
                }
              </ul>
            </section>
          </div>
        }
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DiagnosticsPageComponent {
  private readonly system = inject(System);
  private readonly health = inject(Health);
  readonly state = signal<DiagnosticsState>({ status: 'loading' });

  constructor() {
    void this.load();
  }

  get readyState(): Extract<DiagnosticsState, { status: 'ready' }> | null {
    const value = this.state();
    return value.status === 'ready' ? value : null;
  }

  get errorMessage(): string {
    const value = this.state();
    return value.status === 'error' ? value.message : '';
  }

  reload(): void {
    void this.load();
  }

  private async load(): Promise<void> {
    this.state.set({ status: 'loading' });
    const [versionResult, dependenciesResult] = await Promise.all([
      this.system.getApiVersion(),
      this.health.getDependencyHealth(),
    ]);
    if (versionResult.error !== undefined || dependenciesResult.error !== undefined) {
      this.state.set({ status: 'error', message: 'The control plane did not return diagnostics.' });
      return;
    }
    this.state.set({
      status: 'ready',
      version: versionResult.data.data,
      dependencies: dependenciesResult.data,
    });
  }
}
