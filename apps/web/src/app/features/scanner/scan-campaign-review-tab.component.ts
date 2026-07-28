import { DatePipe, JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type {
  CampaignActivityResponse,
  ScanCampaignSummaryResponse,
  ScanTargetResponse,
} from '@platform/api-client';

import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

type ReviewTab = 'activity' | 'overview' | 'targets';

@Component({
  imports: [DatePipe, JsonPipe, RouterLink, EmptyStateComponent, LoadingStateComponent],
  template: `
    @if (loading()) {
      <app-loading-state [label]="'Loading ' + tab + '…'" />
    } @else if (error()) {
      <div class="state-card" role="alert">{{ error() }}</div>
    } @else if (tab === 'overview' && summary(); as item) {
      <section class="page-stack" aria-labelledby="overview-heading">
        <h2 id="overview-heading">Campaign overview</h2>
        <dl class="summary-grid">
          <div>
            <dt>Targets</dt>
            <dd>{{ count(item.target_counts) }}</dd>
          </div>
          <div>
            <dt>Pages</dt>
            <dd>{{ count(item.page_counts) }}</dd>
          </div>
          <div>
            <dt>Visual scans</dt>
            <dd>{{ count(item.page_scan_counts) }}</dd>
          </div>
          <div>
            <dt>Unresolved failures</dt>
            <dd>{{ item.unresolved_failure_count }}</dd>
          </div>
        </dl>
        <section class="surface-card">
          <h3>Page-type distribution</h3>
          <div class="tag-list">
            @for (entry of entries(item.page_type_counts); track entry[0]) {
              <span>{{ entry[0] }} · {{ entry[1] }}</span>
            }
          </div>
        </section>
        <section class="surface-card">
          <h3>Deduplication</h3>
          <p>
            {{ item.deduplication.exact_duplicate_groups }} exact groups,
            {{ item.deduplication.near_duplicate_groups }} near-duplicate groups, and
            {{ item.deduplication.shared_template_groups }} shared templates.
          </p>
        </section>
      </section>
    } @else if (tab === 'targets') {
      <section aria-labelledby="targets-heading">
        <div class="section-heading">
          <h2 id="targets-heading">Targets</h2>
          <a class="primary-button" routerLink="../import-targets">Import targets</a>
        </div>
        @if (targets().length === 0) {
          <app-empty-state
            heading="No targets"
            message="Import authorized domains before starting the campaign."
          />
        } @else {
          <div class="table-scroll">
            <table class="data-table">
              <caption class="visually-hidden">
                Campaign targets
              </caption>
              <thead>
                <tr>
                  <th scope="col">Domain</th>
                  <th scope="col">Submitted URL</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                @for (target of targets(); track target.id) {
                  <tr>
                    <th scope="row">{{ target.source_domain }}</th>
                    <td>{{ target.normalized_url }}</td>
                    <td>
                      <span class="status-pill" [attr.data-state]="target.status">{{
                        target.status
                      }}</span>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </section>
    } @else if (tab === 'activity') {
      <section aria-labelledby="activity-heading">
        <h2 id="activity-heading">Workflow activity</h2>
        @if (activity().length === 0) {
          <app-empty-state
            heading="No activity yet"
            message="Durable workflow events will appear after the campaign is queued."
          />
        } @else {
          <ol class="activity-list">
            @for (event of activity(); track event.id) {
              <li>
                <div>
                  <strong>{{ event.event_type }}</strong
                  ><span class="status-pill" [attr.data-state]="event.status">{{
                    event.status
                  }}</span>
                </div>
                <time [dateTime]="event.created_at">{{ event.created_at | date: 'medium' }}</time>
                <details>
                  <summary>Event metadata</summary>
                  <pre>{{ event.payload | json }}</pre>
                </details>
              </li>
            }
          </ol>
        }
      </section>
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanCampaignReviewTabComponent {
  private readonly api = inject(ScanReviewApiService);
  private readonly route = inject(ActivatedRoute);
  readonly tab = this.route.snapshot.data['tab'] as ReviewTab;
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly summary = signal<ScanCampaignSummaryResponse | null>(null);
  readonly targets = signal<readonly ScanTargetResponse[]>([]);
  readonly activity = signal<readonly CampaignActivityResponse[]>([]);
  private readonly projectId = this.param('projectId');
  private readonly campaignId = this.param('campaignId');

  constructor() {
    void this.load();
  }
  count(values: Record<string, number>): number {
    return Object.values(values).reduce((sum, value) => sum + value, 0);
  }
  entries(values: Record<string, number>): [string, number][] {
    return Object.entries(values);
  }
  private async load(): Promise<void> {
    try {
      if (this.tab === 'overview')
        this.summary.set(await this.api.summary(this.projectId, this.campaignId));
      else if (this.tab === 'targets')
        this.targets.set((await this.api.targets(this.projectId, this.campaignId)).items);
      else this.activity.set((await this.api.activity(this.projectId, this.campaignId)).items);
    } catch (error: unknown) {
      this.error.set(
        error instanceof Error ? error.message : 'Campaign results could not be loaded.',
      );
    } finally {
      this.loading.set(false);
    }
  }
  private param(name: string): string {
    for (const route of [...this.route.pathFromRoot].reverse()) {
      const value = route.snapshot.paramMap.get(name);
      if (value) return value;
    }
    return '';
  }
}
