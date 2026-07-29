import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import type {
  DatasetBuildResponse,
  DatasetItemResponse,
  DatasetVersionDetailResponse,
} from '@platform/api-client';

import { DatasetApiService } from '../../core/datasets/dataset-api.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="version-heading">
      @if (loading()) {
        <app-loading-state label="Loading dataset version…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (detail(); as current) {
        <header class="page-header">
          <div>
            <p class="eyebrow">{{ current.dataset.name }} · {{ current.version.status }}</p>
            <h1 id="version-heading">Version {{ current.version.version_number }}</h1>
            <p>Manifest {{ current.version.manifest_sha256 || 'not sealed' }}</p>
          </div>
          @if (current.version.status === 'draft') {
            <button class="primary-button" type="button" [disabled]="building()" (click)="build()">
              {{ building() ? 'Starting…' : 'Build and seal version' }}
            </button>
          }
        </header>
        @if (activeBuild(); as build) {
          <div class="state-card" role="status">
            Dataset build: {{ build.status }} · {{ build.stage }}
            @if (
              build.status !== 'succeeded' &&
              build.status !== 'failed' &&
              build.status !== 'cancelled'
            ) {
              <button type="button" (click)="refreshBuild()">Refresh status</button>
            }
          </div>
        }
        <dl class="summary-grid">
          <div>
            <dt>Items</dt>
            <dd>{{ current.version.statistics['item_count'] || 0 }}</dd>
          </div>
          <div>
            <dt>Domains</dt>
            <dd>{{ current.version.statistics['source_domain_count'] || 0 }}</dd>
          </div>
          <div>
            <dt>Schema</dt>
            <dd>{{ current.version.schema_version }}</dd>
          </div>
          <div>
            <dt>Quality</dt>
            <dd>{{ current.quality_report?.status || 'Pending' }}</dd>
          </div>
        </dl>
        <section class="surface-card" aria-labelledby="items-heading">
          <h2 id="items-heading">Dataset items</h2>
          @if (items().length === 0) {
            <app-empty-state
              heading="No items yet"
              message="Items are materialized after the dataset build passes every quality check."
            />
          } @else {
            <div class="table-scroll">
              <table class="data-table">
                <thead>
                  <tr>
                    <th scope="col">Type</th>
                    <th scope="col">Domain</th>
                    <th scope="col">Split</th>
                    <th scope="col">Category</th>
                    <th scope="col">Availability</th>
                  </tr>
                </thead>
                <tbody>
                  @for (item of items(); track item.id) {
                    <tr>
                      <td>{{ item.item_type }}</td>
                      <td>{{ item.source_domain }}</td>
                      <td>{{ item.split }}</td>
                      <td>{{ item.category }}</td>
                      <td>{{ item.availability_status }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        </section>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DatasetVersionDetailComponent {
  private readonly api = inject(DatasetApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly projectId = this.route.snapshot.paramMap.get('projectId') ?? '';
  private readonly datasetId = this.route.snapshot.paramMap.get('datasetId') ?? '';
  private readonly versionId = this.route.snapshot.paramMap.get('versionId') ?? '';
  readonly detail = signal<DatasetVersionDetailResponse | null>(null);
  readonly items = signal<readonly DatasetItemResponse[]>([]);
  readonly loading = signal(true);
  readonly building = signal(false);
  readonly activeBuild = signal<DatasetBuildResponse | null>(null);
  readonly error = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  async build(): Promise<void> {
    const current = this.detail();
    if (current === null) return;
    this.building.set(true);
    try {
      this.activeBuild.set(
        await this.api.startBuild(this.projectId, this.datasetId, current.version),
      );
    } catch (error: unknown) {
      this.error.set(
        error instanceof Error ? error.message : 'The dataset build could not be started.',
      );
    } finally {
      this.building.set(false);
    }
  }

  async refreshBuild(): Promise<void> {
    const build = this.activeBuild();
    if (build === null) return;
    try {
      const refreshed = await this.api.build(
        this.projectId,
        this.datasetId,
        this.versionId,
        build.id,
      );
      this.activeBuild.set(refreshed);
      if (refreshed.status === 'succeeded') await this.load();
    } catch (error: unknown) {
      this.error.set(
        error instanceof Error ? error.message : 'The dataset build could not be loaded.',
      );
    }
  }

  private async load(): Promise<void> {
    try {
      const [detail, items] = await Promise.all([
        this.api.version(this.projectId, this.datasetId, this.versionId),
        this.api.items(this.projectId, this.datasetId, this.versionId),
      ]);
      this.detail.set(detail);
      this.items.set(items.items);
    } catch (error: unknown) {
      this.error.set(
        error instanceof Error ? error.message : 'The dataset version could not be loaded.',
      );
    } finally {
      this.loading.set(false);
    }
  }
}
