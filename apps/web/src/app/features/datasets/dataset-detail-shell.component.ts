import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import type { DatasetResponse, DatasetVersionResponse } from '@platform/api-client';

import { DatasetApiService } from '../../core/datasets/dataset-api.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [RouterLink, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="dataset-heading">
      @if (loading()) {
        <app-loading-state label="Loading dataset…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (dataset(); as current) {
        <header class="page-header">
          <div>
            <p class="eyebrow">Dataset · {{ current.status }}</p>
            <h1 id="dataset-heading">{{ current.name }}</h1>
            <p>{{ current.description || current.purpose }}</p>
          </div>
          @if (current.status === 'active') {
            <button
              class="primary-button"
              type="button"
              [disabled]="creating()"
              (click)="createVersion()"
            >
              {{ creating() ? 'Creating…' : 'Create draft version' }}
            </button>
          }
        </header>
        <dl class="summary-grid">
          <div>
            <dt>Minimum confidence</dt>
            <dd>{{ current.minimum_confidence }}</dd>
          </div>
          <div>
            <dt>Approval</dt>
            <dd>{{ current.require_approved ? 'Required' : 'Optional' }}</dd>
          </div>
          <div>
            <dt>Item types</dt>
            <dd>{{ current.item_types?.join(', ') }}</dd>
          </div>
          <div>
            <dt>Provenance</dt>
            <dd>{{ current.provenance_requirements?.join(', ') }}</dd>
          </div>
        </dl>
        <section class="surface-card" aria-labelledby="versions-heading">
          <h2 id="versions-heading">Versions</h2>
          @if (versions().length === 0) {
            <app-empty-state
              heading="No versions"
              message="Create a draft to capture this selection policy."
            />
          } @else {
            <ol class="activity-list">
              @for (version of versions(); track version.id) {
                <li>
                  <div>
                    <a [routerLink]="['versions', version.id]"
                      ><strong>Version {{ version.version_number }}</strong></a
                    >
                    <span class="status-pill" [attr.data-state]="version.status">{{
                      version.status
                    }}</span>
                  </div>
                  <span>{{ version.statistics['item_count'] || 0 }} items</span>
                  <span>
                    {{
                      version.sealed_at
                        ? 'Sealed ' + formatDate(version.sealed_at)
                        : 'Draft created ' + formatDate(version.created_at)
                    }}
                  </span>
                </li>
              }
            </ol>
          }
        </section>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DatasetDetailShellComponent {
  private readonly api = inject(DatasetApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly projectId = this.route.snapshot.paramMap.get('projectId') ?? '';
  private readonly datasetId = this.route.snapshot.paramMap.get('datasetId') ?? '';
  readonly dataset = signal<DatasetResponse | null>(null);
  readonly versions = signal<readonly DatasetVersionResponse[]>([]);
  readonly loading = signal(true);
  readonly creating = signal(false);
  readonly error = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  formatDate(value: string): string {
    return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(new Date(value));
  }

  async createVersion(): Promise<void> {
    this.creating.set(true);
    try {
      const version = await this.api.createVersion(this.projectId, this.datasetId);
      await this.router.navigate(['versions', version.id], { relativeTo: this.route });
    } catch (error: unknown) {
      this.error.set(
        error instanceof Error ? error.message : 'The draft version could not be created.',
      );
    } finally {
      this.creating.set(false);
    }
  }

  private async load(): Promise<void> {
    try {
      const [dataset, versions] = await Promise.all([
        this.api.get(this.projectId, this.datasetId),
        this.api.versions(this.projectId, this.datasetId),
      ]);
      this.dataset.set(dataset);
      this.versions.set(versions.items);
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'The dataset could not be loaded.');
    } finally {
      this.loading.set(false);
    }
  }
}
