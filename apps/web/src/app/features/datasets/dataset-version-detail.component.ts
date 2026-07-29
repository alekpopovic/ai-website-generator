import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import type { OnDestroy } from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import type {
  DatasetBuildResponse,
  DatasetItemResponse,
  DatasetVersionDetailResponse,
  DatasetVersionResponse,
  JsonValueOutput,
} from '@platform/api-client';

import { DatasetApiService } from '../../core/datasets/dataset-api.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';
import { DatasetPatternCuratorComponent } from './dataset-pattern-curator.component';

const TERMINAL_BUILD_STATES = new Set(['cancelled', 'failed', 'succeeded']);

@Component({
  imports: [
    CommonModule,
    ReactiveFormsModule,
    DatasetPatternCuratorComponent,
    EmptyStateComponent,
    LoadingStateComponent,
  ],
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
          <section
            class="build-progress surface-card"
            aria-labelledby="build-progress-heading"
            aria-live="polite"
          >
            <div class="section-heading">
              <div>
                <h2 id="build-progress-heading">Build progress</h2>
                <p>{{ build.status }} · {{ stageLabel(build.stage) }}</p>
              </div>
              <strong>{{ progress(build) }}%</strong>
            </div>
            <progress [value]="progress(build)" max="100">{{ progress(build) }}%</progress>
            @if (build.failure_code) {
              <p class="field-error" role="alert">Build stopped: {{ build.failure_code }}</p>
            }
            <div class="button-row">
              @if (!terminal(build)) {
                <button type="button" (click)="cancelBuild(build)">Cancel build</button>
              }
              @if (build.status === 'failed' || build.status === 'cancelled') {
                <button type="button" (click)="retryBuild(build)">Retry build</button>
              }
            </div>
          </section>
        }

        <dl class="summary-grid">
          <div>
            <dt>Items</dt>
            <dd>{{ numberStat('item_count') }}</dd>
          </div>
          <div>
            <dt>Domains</dt>
            <dd>{{ numberStat('source_domain_count') }}</dd>
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

        @if (current.version.status === 'draft') {
          <section class="surface-card page-stack" aria-labelledby="draft-policy-heading">
            <div class="section-heading">
              <div>
                <h2 id="draft-policy-heading">Draft selection policy</h2>
                <p>Changes affect the next build and never mutate sealed versions.</p>
              </div>
            </div>
            <form
              class="filter-grid"
              [formGroup]="policyForm"
              (ngSubmit)="savePolicy(current.version)"
            >
              <label
                >Minimum confidence<input
                  formControlName="minimumConfidence"
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
              /></label>
              <label
                >Categories<input formControlName="categories" placeholder="homepage, pricing"
              /></label>
              <label>Languages<input formControlName="languages" placeholder="en, de" /></label>
              <label class="checkbox-label"
                ><input formControlName="requireApproved" type="checkbox" />Approved patterns
                only</label
              >
              <label
                >Provenance<select formControlName="provenance">
                  <option value="authorized">Authorized only</option>
                  <option value="restricted">Restricted</option>
                </select></label
              >
              <div class="filter-actions">
                <button class="primary-button" type="submit" [disabled]="savingPolicy()">
                  {{ savingPolicy() ? 'Saving…' : 'Save draft policy' }}
                </button>
              </div>
            </form>
          </section>
          <app-dataset-pattern-curator [projectId]="projectId" />
        }

        <section class="surface-card page-stack" aria-labelledby="quality-heading">
          <div class="section-heading">
            <div>
              <h2 id="quality-heading">Quality report</h2>
              <p>Computed by the build worker from server-side aggregates.</p>
            </div>
            <span
              class="status-pill"
              [attr.data-state]="current.quality_report?.status || 'pending'"
              >{{ current.quality_report?.status || 'pending' }}</span
            >
          </div>
          @if (sourceWarning()) {
            <div class="warning-banner" role="alert">
              <strong>Source concentration warning.</strong> {{ sourceWarning() }}
            </div>
          }
          @if (provenanceWarning()) {
            <div class="warning-banner" role="alert">
              <strong>Provenance warning.</strong> {{ provenanceWarning() }}
            </div>
          }
          @if (current.quality_report; as report) {
            @if (report.findings.length) {
              <ul class="finding-list">
                @for (finding of report.findings; track finding['code']) {
                  <li>
                    <strong>{{ finding['code'] }}</strong
                    ><span>{{ finding['message'] }}</span>
                  </li>
                }
              </ul>
            } @else {
              <p>No quality findings. Required checks passed.</p>
            }
          } @else {
            <p>Run a build to produce the immutable quality report and split statistics.</p>
          }
        </section>

        <section class="surface-card page-stack" aria-labelledby="distribution-heading">
          <h2 id="distribution-heading">Distributions</h2>
          <div class="chart-grid">
            @for (chart of charts(); track chart.name) {
              <section class="mini-chart" [attr.aria-label]="chart.label + ' distribution'">
                <h3>{{ chart.label }}</h3>
                @if (!chart.values.length) {
                  <p>Pending build</p>
                }
                @for (entry of chart.values; track entry.label) {
                  <div class="bar-row">
                    <span>{{ entry.label }}</span
                    ><span class="bar-track"
                      ><span class="bar-fill" [style.width.%]="entry.percent"></span></span
                    ><strong>{{ entry.count }}</strong>
                  </div>
                }
              </section>
            }
          </div>
        </section>

        <section class="surface-card" aria-labelledby="splits-heading">
          <h2 id="splits-heading">Train, validation, and test splits</h2>
          <dl class="summary-grid">
            <div>
              <dt>Train</dt>
              <dd>{{ distributionValue('splits', 'train') }}</dd>
            </div>
            <div>
              <dt>Validation</dt>
              <dd>{{ distributionValue('splits', 'validation') }}</dd>
            </div>
            <div>
              <dt>Test</dt>
              <dd>{{ distributionValue('splits', 'test') }}</dd>
            </div>
            <div>
              <dt>Domain leakage</dt>
              <dd>{{ numberStat('source_domain_leakage_count') }}</dd>
            </div>
          </dl>
        </section>

        <section class="surface-card" aria-labelledby="items-heading">
          <h2 id="items-heading">Materialized items</h2>
          @if (!items().length) {
            <app-empty-state
              heading="No items yet"
              message="Items are materialized only after every required build check passes."
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
export class DatasetVersionDetailComponent implements OnDestroy {
  private readonly api = inject(DatasetApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly notifications = inject(NotificationService);
  readonly projectId = this.route.snapshot.paramMap.get('projectId') ?? '';
  private readonly datasetId = this.route.snapshot.paramMap.get('datasetId') ?? '';
  private readonly versionId = this.route.snapshot.paramMap.get('versionId') ?? '';
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  readonly detail = signal<DatasetVersionDetailResponse | null>(null);
  readonly items = signal<readonly DatasetItemResponse[]>([]);
  readonly loading = signal(true);
  readonly building = signal(false);
  readonly savingPolicy = signal(false);
  readonly activeBuild = signal<DatasetBuildResponse | null>(null);
  readonly error = signal<string | null>(null);
  readonly policyForm = inject(FormBuilder).nonNullable.group({
    minimumConfidence: [0.7, [Validators.min(0), Validators.max(1)]],
    categories: [''],
    languages: [''],
    requireApproved: [true],
    provenance: new FormControl<'authorized' | 'restricted'>('authorized', { nonNullable: true }),
  });
  readonly charts = computed(() =>
    ['categories', 'languages', 'section_types', 'layouts', 'styles'].map((name) => ({
      name,
      label: name.replace('_', ' ').replace(/\b\w/g, (value) => value.toUpperCase()),
      values: this.chartValues(name),
    })),
  );
  private readonly stages = [
    'queued',
    'validate-selection-policy',
    'resolve-candidate-patterns',
    'exclude-ineligible-patterns',
    'deduplicate-pattern-hashes',
    'check-provenance-authorization',
    'check-source-specific-copy',
    'compute-distributions',
    'create-domain-disjoint-splits',
    'produce-quality-report',
    'materialize-version-manifest',
    'enqueue-missing-embeddings',
    'seal-dataset-version',
    'complete',
  ];

  constructor() {
    void this.load();
  }
  ngOnDestroy(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
  }
  terminal(build: DatasetBuildResponse): boolean {
    return TERMINAL_BUILD_STATES.has(build.status);
  }
  stageLabel(stage: string): string {
    return stage.replaceAll('-', ' ');
  }
  progress(build: DatasetBuildResponse): number {
    if (build.status === 'succeeded') return 100;
    const index = this.stages.indexOf(build.stage);
    return index < 0 ? 0 : Math.round((index / (this.stages.length - 1)) * 100);
  }

  async build(): Promise<void> {
    const current = this.detail();
    if (!current) return;
    this.building.set(true);
    try {
      const build = await this.api.startBuild(this.projectId, this.datasetId, current.version);
      this.activeBuild.set(build);
      this.schedulePoll();
    } catch (error: unknown) {
      this.notifications.error(message(error));
    } finally {
      this.building.set(false);
    }
  }
  async cancelBuild(build: DatasetBuildResponse): Promise<void> {
    try {
      this.activeBuild.set(
        await this.api.cancelBuild(this.projectId, this.datasetId, this.versionId, build),
      );
      this.schedulePoll();
    } catch (error: unknown) {
      this.notifications.error(message(error));
    }
  }
  async retryBuild(build: DatasetBuildResponse): Promise<void> {
    try {
      this.activeBuild.set(
        await this.api.retryBuild(this.projectId, this.datasetId, this.versionId, build.id),
      );
      this.schedulePoll();
    } catch (error: unknown) {
      this.notifications.error(message(error));
    }
  }

  async savePolicy(version: DatasetVersionResponse): Promise<void> {
    if (this.policyForm.invalid) return;
    this.savingPolicy.set(true);
    const value = this.policyForm.getRawValue();
    try {
      const updated = await this.api.updateVersion(this.projectId, this.datasetId, this.versionId, {
        version: version.version,
        selection_policy: {
          ...version.selection_config,
          category_filters: splitValues(value.categories),
          language_filters: splitValues(value.languages),
          minimum_confidence: value.minimumConfidence,
          require_approved: value.requireApproved,
          provenance_requirements: [value.provenance],
        },
      });
      this.detail.update((current) => (current ? { ...current, version: updated } : current));
      this.notifications.success('Draft selection policy saved.');
    } catch (error: unknown) {
      this.notifications.error(message(error));
    } finally {
      this.savingPolicy.set(false);
    }
  }

  numberStat(name: string): number {
    const value = this.statistics()[name];
    return typeof value === 'number' ? value : 0;
  }
  distributionValue(name: string, key: string): number {
    return this.distribution(name)[key] ?? 0;
  }
  sourceWarning(): string | null {
    const share = this.statistics()['largest_domain_share'];
    return typeof share === 'number' && share > 0.6
      ? `${String(Math.round(share * 100))}% of items depend on one domain.`
      : null;
  }
  provenanceWarning(): string | null {
    const excluded = this.distribution('excluded');
    const count =
      (excluded['unauthorized_provenance'] ?? 0) +
      (excluded['suppressed'] ?? 0) +
      (excluded['removed'] ?? 0);
    return count > 0
      ? `${String(count)} candidate patterns were excluded by provenance or removal controls.`
      : null;
  }

  private async refreshBuild(): Promise<void> {
    const build = this.activeBuild();
    if (!build) return;
    try {
      const refreshed = await this.api.build(
        this.projectId,
        this.datasetId,
        this.versionId,
        build.id,
      );
      this.activeBuild.set(refreshed);
      if (this.terminal(refreshed)) {
        if (refreshed.status === 'succeeded') await this.load(false);
      } else this.schedulePoll();
    } catch (error: unknown) {
      this.notifications.error(message(error));
    }
  }
  private schedulePoll(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    const build = this.activeBuild();
    if (build && !this.terminal(build))
      this.pollTimer = setTimeout(() => void this.refreshBuild(), 1500);
  }
  private async load(showLoading = true): Promise<void> {
    if (showLoading) this.loading.set(true);
    try {
      const [detail, items] = await Promise.all([
        this.api.version(this.projectId, this.datasetId, this.versionId),
        this.api.items(this.projectId, this.datasetId, this.versionId),
      ]);
      this.detail.set(detail);
      this.items.set(items.items);
      const policy = detail.version.selection_config;
      this.policyForm.setValue({
        minimumConfidence: policy.minimum_confidence ?? 0.7,
        categories: (policy.category_filters ?? []).join(', '),
        languages: (policy.language_filters ?? []).join(', '),
        requireApproved: policy.require_approved ?? true,
        provenance: policy.provenance_requirements?.[0] ?? 'authorized',
      });
    } catch (error: unknown) {
      this.error.set(message(error));
    } finally {
      this.loading.set(false);
    }
  }
  private statistics(): Record<string, JsonValueOutput> {
    return this.detail()?.quality_report?.statistics ?? this.detail()?.version.statistics ?? {};
  }
  private distribution(name: string): Record<string, number> {
    const value = this.statistics()[name];
    if (!value || Array.isArray(value) || typeof value !== 'object') return {};
    return Object.fromEntries(
      Object.entries(value).filter(
        (entry): entry is [string, number] => typeof entry[1] === 'number',
      ),
    );
  }
  private chartValues(name: string): readonly { label: string; count: number; percent: number }[] {
    const values = this.distribution(name);
    const maximum = Math.max(1, ...Object.values(values));
    return Object.entries(values)
      .map(([label, count]) => ({ label, count, percent: (count / maximum) * 100 }))
      .slice(0, 8);
  }
}

function splitValues(value: string): string[] {
  return [
    ...new Set(
      value
        .split(',')
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
    ),
  ];
}
function message(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
}
