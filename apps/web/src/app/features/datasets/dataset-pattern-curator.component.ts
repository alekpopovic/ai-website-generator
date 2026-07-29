import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import type { OnDestroy } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import type {
  SectionPatternDetailResponse,
  SectionPatternFacetsResponse,
  SectionPatternResponse,
} from '@platform/api-client';

import {
  AnalysisReviewApiService,
  type ApprovalState,
  type PatternFilterQuery,
} from '../../core/analysis/analysis-review-api.service';
import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  selector: 'app-dataset-pattern-curator',
  imports: [CommonModule, ReactiveFormsModule, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="pattern-curation-heading">
      <div class="section-heading">
        <div>
          <h2 id="pattern-curation-heading">Pattern curation</h2>
          <p>Filter and review normalized patterns before building this draft.</p>
        </div>
        <span aria-live="polite">{{ total() }} matching patterns</span>
      </div>

      <form class="filter-grid" [formGroup]="filters" (ngSubmit)="applyFilters()">
        <label
          >Domain<select formControlName="domain">
            <option value="">All</option>
            @for (item of facets()?.domains || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
        >
        <label
          >Category<select formControlName="category">
            <option value="">All</option>
            @for (item of facets()?.categories || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
        >
        <label
          >Page type<select formControlName="pageType">
            <option value="">All</option>
            @for (item of facets()?.page_types || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
        >
        <label
          >Section type<select formControlName="sectionType">
            <option value="">All</option>
            @for (item of facets()?.section_types || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
        >
        <label
          >Layout<select formControlName="layout">
            <option value="">All</option>
            @for (item of facets()?.layouts || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
        >
        <label
          >Language<select formControlName="language">
            <option value="">All</option>
            @for (item of facets()?.languages || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
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
          >Maximum confidence<input
            formControlName="maximumConfidence"
            type="number"
            min="0"
            max="1"
            step="0.05"
        /></label>
        <label
          >Approval<select formControlName="approval">
            <option value="">All</option>
            @for (item of facets()?.approvals || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
        >
        <label
          >Provenance<select formControlName="provenance">
            <option value="">All</option>
            @for (item of facets()?.provenance || []; track item.value) {
              <option [value]="item.value">{{ item.value }} ({{ item.count }})</option>
            }
          </select></label
        >
        <div class="button-row filter-actions">
          <button class="primary-button" type="submit">Apply filters</button>
          <button class="secondary-button" type="button" (click)="clearFilters()">Clear</button>
        </div>
      </form>

      @if (selectedCount() > 0) {
        <div class="bulk-toolbar" role="toolbar" aria-label="Bulk curation actions">
          <strong>{{ selectedCount() }} selected</strong>
          <button type="button" (click)="bulkCurate('approved')">Approve</button>
          <button type="button" (click)="bulkCurate('needs_review')">Mark for review</button>
          <button type="button" class="danger-button" (click)="bulkCurate('rejected')">
            Reject
          </button>
          <button type="button" (click)="clearSelection()">Clear selection</button>
        </div>
      }

      @if (loading()) {
        <app-loading-state label="Loading patterns…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (patterns().length === 0) {
        <app-empty-state
          heading="No matching patterns"
          message="Change the filters or analyze more pages."
        />
      } @else {
        <div class="curation-layout">
          <div class="table-scroll">
            <table class="data-table" aria-label="Matching patterns">
              <thead>
                <tr>
                  <th scope="col"><span class="visually-hidden">Select</span></th>
                  <th scope="col">Pattern</th>
                  <th scope="col">Category</th>
                  <th scope="col">Layout</th>
                  <th scope="col">Language</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Review</th>
                  <th scope="col">Provenance</th>
                </tr>
              </thead>
              <tbody>
                @for (pattern of patterns(); track pattern.id; let index = $index) {
                  <tr [class.selected-row]="detail()?.pattern?.id === pattern.id">
                    <td>
                      <input
                        type="checkbox"
                        [attr.aria-label]="'Select ' + pattern.section_type + ' pattern'"
                        [checked]="selectedIds().has(pattern.id)"
                        (change)="toggle(pattern.id)"
                      />
                    </td>
                    <th scope="row">
                      <button
                        class="table-link"
                        type="button"
                        [id]="'pattern-row-' + index"
                        (click)="open(pattern)"
                        (keydown.arrowdown)="moveFocus(index, 1, $event)"
                        (keydown.arrowup)="moveFocus(index, -1, $event)"
                      >
                        {{ pattern.section_type }}
                      </button>
                    </th>
                    <td>{{ pattern.category }}</td>
                    <td>{{ pattern.layout }}</td>
                    <td>{{ pattern.language }}</td>
                    <td>{{ pattern.confidence | percent }}</td>
                    <td>{{ pattern.approval_state }}</td>
                    <td>
                      <span class="status-pill" [attr.data-state]="pattern.provenance_state">{{
                        pattern.provenance_state
                      }}</span>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
            <nav class="pagination-row" aria-label="Pattern pages">
              <button type="button" [disabled]="offset() === 0" (click)="page(-1)">Previous</button>
              <span>{{ offset() + 1 }}–{{ pageEnd() }} of {{ total() }}</span>
              <button type="button" [disabled]="pageEnd() >= total()" (click)="page(1)">
                Next
              </button>
            </nav>
          </div>

          <aside class="pattern-inspector" aria-labelledby="pattern-detail-heading">
            @if (detailLoading()) {
              <app-loading-state label="Loading pattern detail…" />
            } @else if (detail(); as current) {
              <div class="section-heading">
                <h3 id="pattern-detail-heading">{{ current.pattern.section_type }} pattern</h3>
                <span>{{ current.pattern.approval_state }}</span>
              </div>
              @if (current.pattern.provenance_state !== 'authorized') {
                <div class="warning-banner" role="alert">
                  This source is {{ current.pattern.provenance_state }} and cannot enter an
                  authorized build.
                </div>
              }
              @if (screenshotUrl()) {
                <img
                  class="source-screenshot"
                  [src]="screenshotUrl()"
                  alt="Source page screenshot for visual review"
                />
              } @else {
                <p class="muted-copy">No safe screenshot is available.</p>
              }
              <h4>Abstract pattern</h4>
              <dl class="detail-list">
                <div>
                  <dt>Purpose</dt>
                  <dd>{{ current.pattern.pattern.copy_purpose }}</dd>
                </div>
                <div>
                  <dt>Components</dt>
                  <dd>{{ componentNames(current) }}</dd>
                </div>
                <div>
                  <dt>Styles</dt>
                  <dd>{{ current.pattern.style_tags.join(', ') || 'None' }}</dd>
                </div>
              </dl>
              <h4>Design tokens</h4>
              @if (current.design_tokens; as tokens) {
                <div class="token-swatches" aria-label="Color tokens">
                  @for (color of tokens.colors.palette; track color.name) {
                    <span [style.background]="color.value" [title]="color.name + ': ' + color.value"
                      ><span class="visually-hidden">{{ color.name }} {{ color.value }}</span></span
                    >
                  }
                </div>
                <p>
                  {{
                    (tokens.typography.font_families || []).join(', ') || 'No typography categories'
                  }}
                  · {{ (tokens.spacing.scale_px || []).join(', ') || 'No spacing scale' }}
                </p>
              } @else {
                <p class="muted-copy">Website-level tokens are unavailable.</p>
              }
              <h4>Source metadata</h4>
              <dl class="detail-list">
                <div>
                  <dt>Domain</dt>
                  <dd>{{ current.source.domain }}</dd>
                </div>
                <div>
                  <dt>Page</dt>
                  <dd class="break-text">{{ current.source.final_url || current.source.url }}</dd>
                </div>
                <div>
                  <dt>HTTP</dt>
                  <dd>{{ current.source.http_status || 'Unknown' }}</dd>
                </div>
              </dl>
              <h4>Analysis and embedding</h4>
              <dl class="detail-list">
                <div>
                  <dt>Analyzer</dt>
                  <dd>{{ current.analysis.analyzer_version }}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>{{ current.analysis.model_name }}</dd>
                </div>
                <div>
                  <dt>Embedding</dt>
                  <dd>{{ current.embedding?.status || 'Not indexed' }}</dd>
                </div>
              </dl>
              <div class="button-row" role="group" aria-label="Pattern curation">
                <button type="button" (click)="curate(current.pattern, 'approved')">Approve</button>
                <button type="button" (click)="curate(current.pattern, 'needs_review')">
                  Mark for review
                </button>
                <button
                  type="button"
                  class="danger-button"
                  (click)="curate(current.pattern, 'rejected')"
                >
                  Reject
                </button>
              </div>
            } @else {
              <p>Select a pattern to inspect it.</p>
            }
          </aside>
        </div>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DatasetPatternCuratorComponent implements OnDestroy {
  readonly projectId = input.required<string>();
  private readonly api = inject(AnalysisReviewApiService);
  private readonly scans = inject(ScanReviewApiService);
  private readonly notifications = inject(NotificationService);
  readonly filters = inject(FormBuilder).nonNullable.group({
    domain: [''],
    category: [''],
    pageType: [''],
    sectionType: [''],
    layout: [''],
    language: [''],
    minimumConfidence: [''],
    maximumConfidence: [''],
    approval: [''],
    provenance: [''],
  });
  readonly patterns = signal<readonly SectionPatternResponse[]>([]);
  readonly facets = signal<SectionPatternFacetsResponse | null>(null);
  readonly detail = signal<SectionPatternDetailResponse | null>(null);
  readonly screenshotUrl = signal<string | null>(null);
  readonly selectedIds = signal<ReadonlySet<string>>(new Set());
  readonly loading = signal(true);
  readonly detailLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly offset = signal(0);
  readonly total = signal(0);
  readonly selectedCount = computed(() => this.selectedIds().size);
  readonly pageEnd = computed(() => Math.min(this.offset() + this.patterns().length, this.total()));

  constructor() {
    queueMicrotask(() => void this.load());
  }
  ngOnDestroy(): void {
    this.revokeScreenshot();
  }

  async applyFilters(): Promise<void> {
    this.offset.set(0);
    await this.load();
  }
  clearFilters(): void {
    this.filters.reset();
    void this.applyFilters();
  }
  async page(direction: -1 | 1): Promise<void> {
    this.offset.update((value) => Math.max(0, value + direction * 100));
    await this.load();
  }
  toggle(id: string): void {
    const next = new Set(this.selectedIds());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.selectedIds.set(next);
  }
  clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  async open(pattern: SectionPatternResponse): Promise<void> {
    this.detailLoading.set(true);
    this.revokeScreenshot();
    try {
      const detail = await this.api.patternDetail(this.projectId(), pattern.id);
      this.detail.set(detail);
      if (detail.screenshot) {
        const blob = await this.scans.screenshot(
          this.projectId(),
          detail.screenshot.campaign_id,
          detail.screenshot.artifact_id,
        );
        this.screenshotUrl.set(URL.createObjectURL(blob));
      }
    } catch (error: unknown) {
      this.notifications.error(message(error));
    } finally {
      this.detailLoading.set(false);
    }
  }

  async curate(pattern: SectionPatternResponse, state: ApprovalState): Promise<void> {
    try {
      const updated = await this.api.curatePattern(this.projectId(), pattern, state, null);
      this.replacePatterns([updated]);
      await this.open(updated);
      this.notifications.success('Pattern review updated.');
    } catch (error: unknown) {
      this.notifications.error(message(error));
    }
  }

  async bulkCurate(state: ApprovalState): Promise<void> {
    const selected = this.patterns().filter((item) => this.selectedIds().has(item.id));
    if (!selected.length) return;
    try {
      const updated = await this.api.curatePatterns(this.projectId(), selected, state, null);
      this.replacePatterns(updated);
      this.selectedIds.set(new Set());
      this.notifications.success(`${String(updated.length)} patterns updated.`);
    } catch (error: unknown) {
      this.notifications.error(message(error));
    }
  }

  moveFocus(index: number, delta: -1 | 1, event: Event): void {
    event.preventDefault();
    const next = Math.max(0, Math.min(this.patterns().length - 1, index + delta));
    document.getElementById(`pattern-row-${String(next)}`)?.focus();
  }

  componentNames(detail: SectionPatternDetailResponse): string {
    const names = (detail.pattern.pattern.components ?? [])
      .map((item) => item.component_name)
      .join(', ');
    return names.length ? names : 'None';
  }

  private query(): PatternFilterQuery {
    const value = this.filters.getRawValue();
    const query: Record<string, string | number> = {};
    const values: Record<string, string> = {
      domain: value.domain,
      category: value.category,
      page_type: value.pageType,
      section_type: value.sectionType,
      layout: value.layout,
      language: value.language,
      approval_state: value.approval,
      provenance_state: value.provenance,
    };
    for (const [key, entry] of Object.entries(values)) if (entry) query[key] = entry;
    if (value.minimumConfidence !== '')
      query['minimum_confidence'] = Number(value.minimumConfidence);
    if (value.maximumConfidence !== '')
      query['maximum_confidence'] = Number(value.maximumConfidence);
    return query;
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const query = this.query();
      const [page, facets] = await Promise.all([
        this.api.sectionPatterns(this.projectId(), query, this.offset()),
        this.api.patternFacets(this.projectId(), query),
      ]);
      this.patterns.set(page.items);
      this.total.set(page.pagination.total);
      this.facets.set(facets);
      this.selectedIds.set(new Set());
    } catch (error: unknown) {
      this.error.set(message(error));
    } finally {
      this.loading.set(false);
    }
  }

  private replacePatterns(updated: readonly SectionPatternResponse[]): void {
    const byId = new Map(updated.map((item) => [item.id, item]));
    this.patterns.update((items) => items.map((item) => byId.get(item.id) ?? item));
  }
  private revokeScreenshot(): void {
    const value = this.screenshotUrl();
    if (value) URL.revokeObjectURL(value);
    this.screenshotUrl.set(null);
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
}
