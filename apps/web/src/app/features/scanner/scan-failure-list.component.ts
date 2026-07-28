import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import type {
  ListScanCampaignFailuresData,
  ScanCampaignResponse,
  ScanFailureResponse,
} from '@platform/api-client';

import { NotificationService } from '../../core/notifications/notification.service';
import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [ReactiveFormsModule, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="failures-heading">
      <div class="section-heading">
        <div>
          <h2 id="failures-heading">Failures</h2>
          <p>Retry only unresolved failures explicitly marked retryable.</p>
        </div>
        <button
          class="primary-button"
          type="button"
          [disabled]="selected().size === 0 || retrying()"
          (click)="retrySelected()"
        >
          Retry selected ({{ selected().size }})
        </button>
      </div>
      <form class="filter-bar four-filters" [formGroup]="filters" (ngSubmit)="load()">
        <label
          ><span>Stage</span
          ><select class="text-input" formControlName="stage">
            <option value="">All</option>
            @for (stage of stages; track stage) {
              <option [value]="stage">{{ stage }}</option>
            }
          </select></label
        ><label
          ><span>Failure type</span
          ><input class="text-input" formControlName="errorCode" placeholder="timeout" /></label
        ><label class="attestation-field"
          ><input type="checkbox" formControlName="unresolvedOnly" /><span
            >Unresolved only</span
          ></label
        ><button class="secondary-button" type="submit">Apply filters</button>
      </form>
      @if (loading()) {
        <app-loading-state label="Loading failures…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (failures().length === 0) {
        <app-empty-state heading="No failures" message="No scan failures match these filters." />
      } @else {
        <div class="table-scroll">
          <table class="data-table">
            <caption class="visually-hidden">
              Scan failures
            </caption>
            <thead>
              <tr>
                <th scope="col">Select</th>
                <th scope="col">Type</th>
                <th scope="col">Stage</th>
                <th scope="col">Message</th>
                <th scope="col">Retryable</th>
              </tr>
            </thead>
            <tbody>
              @for (failure of failures(); track failure.id) {
                <tr>
                  <td>
                    <input
                      type="checkbox"
                      [attr.aria-label]="'Select ' + failure.error_code"
                      [checked]="selected().has(failure.id)"
                      [disabled]="!failure.retryable || failure.resolved_at !== null"
                      (change)="toggle(failure.id)"
                    />
                  </td>
                  <th scope="row">{{ failure.error_code }}</th>
                  <td>{{ failure.stage }}</td>
                  <td>{{ failure.message }}</td>
                  <td>{{ failure.retryable && failure.resolved_at === null ? 'Yes' : 'No' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanFailureListComponent {
  private readonly api = inject(ScanReviewApiService);
  private readonly notifications = inject(NotificationService);
  private readonly route = inject(ActivatedRoute);
  private readonly formBuilder = inject(FormBuilder);
  readonly stages = ['control', 'crawl', 'browser', 'analysis', 'embedding'] as const;
  readonly failures = signal<readonly ScanFailureResponse[]>([]);
  readonly campaign = signal<ScanCampaignResponse | null>(null);
  readonly selected = signal<ReadonlySet<string>>(new Set());
  readonly loading = signal(true);
  readonly retrying = signal(false);
  readonly error = signal<string | null>(null);
  readonly filters = this.formBuilder.nonNullable.group({
    stage: '',
    errorCode: '',
    unresolvedOnly: true,
  });
  private readonly projectId = this.param('projectId');
  private readonly campaignId = this.param('campaignId');
  constructor() {
    void this.load();
  }
  toggle(id: string): void {
    this.selected.update((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    this.selected.set(new Set());
    const value = this.filters.getRawValue();
    const query: NonNullable<ListScanCampaignFailuresData['query']> = {
      offset: 0,
      limit: 100,
      unresolved_only: value.unresolvedOnly,
    };
    if (value.stage) query.stage = value.stage as NonNullable<typeof query.stage>;
    if (value.errorCode.trim()) query.error_code = value.errorCode.trim();
    try {
      const [campaign, page] = await Promise.all([
        this.api.campaign(this.projectId, this.campaignId),
        this.api.failures(this.projectId, this.campaignId, query),
      ]);
      this.campaign.set(campaign);
      this.failures.set(page.items);
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Failures could not be loaded.');
    } finally {
      this.loading.set(false);
    }
  }
  async retrySelected(): Promise<void> {
    const campaign = this.campaign();
    if (!campaign || this.selected().size === 0) return;
    this.retrying.set(true);
    try {
      this.campaign.set(
        await this.api.retrySelected(this.projectId, campaign, [...this.selected()]),
      );
      this.notifications.success('Selected failures were queued for retry.');
      await this.load();
    } catch (error: unknown) {
      this.notifications.error(
        error instanceof Error ? error.message : 'Failures could not be retried.',
      );
    } finally {
      this.retrying.set(false);
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
