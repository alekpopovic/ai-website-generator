import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import type { PageProfileResponse, SectionPatternResponse } from '@platform/api-client';

import {
  AnalysisReviewApiService,
  type ApprovalState,
} from '../../core/analysis/analysis-review-api.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [FormsModule, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="analysis-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Governed analysis</p>
          <h1 id="analysis-heading">Profiles and section patterns</h1>
          <p>
            Inspect abstract, source-safe model outputs before they become retrieval candidates.
          </p>
        </div>
      </header>

      @if (loading()) {
        <app-loading-state label="Loading analysis profiles…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else {
        <section class="surface-card page-stack" aria-labelledby="profiles-heading">
          <div>
            <h2 id="profiles-heading">Current page profiles</h2>
            <p>Every row links to an immutable analysis run; superseded profiles remain stored.</p>
          </div>
          @if (profiles().length === 0) {
            <app-empty-state
              heading="No page profiles"
              message="Completed page analyses will appear here."
            />
          } @else {
            <div class="table-scroll">
              <table class="data-table">
                <caption class="visually-hidden">
                  Current normalized page profiles
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Page type</th>
                    <th scope="col">Language</th>
                    <th scope="col">Confidence</th>
                    <th scope="col">Model digest</th>
                    <th scope="col">Review</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  @for (profile of profiles(); track profile.id) {
                    <tr>
                      <th scope="row">{{ profile.page_type }}</th>
                      <td>{{ profile.language }}</td>
                      <td>{{ percent(profile.confidence) }}</td>
                      <td>
                        <code>{{ compactDigest(profile.model_digest) }}</code>
                      </td>
                      <td>
                        <span class="status-pill" [attr.data-state]="profile.approval_state">{{
                          profile.approval_state
                        }}</span>
                      </td>
                      <td>
                        <div class="compact-actions">
                          <button
                            class="secondary-button"
                            type="button"
                            (click)="curateProfile(profile, 'approved')"
                          >
                            Approve
                          </button>
                          <button
                            class="secondary-button"
                            type="button"
                            (click)="curateProfile(profile, 'rejected')"
                          >
                            Reject
                          </button>
                          <button
                            class="secondary-button"
                            type="button"
                            (click)="curateProfile(profile, 'needs_review')"
                          >
                            Needs review
                          </button>
                        </div>
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        </section>

        <section class="surface-card page-stack" aria-labelledby="patterns-heading">
          <div class="page-header">
            <div>
              <h2 id="patterns-heading">Section patterns</h2>
              <p>
                Retrieval text is derived only from controlled section, component, layout, and style
                values.
              </p>
            </div>
            <label class="form-field"
              ><span class="field-label">Review state</span>
              <select
                class="text-input"
                [ngModel]="filter()"
                (ngModelChange)="changeFilter($event)"
              >
                <option value="all">All</option>
                <option value="needs_review">Needs review</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
              </select>
            </label>
          </div>
          @if (filteredPatterns().length === 0) {
            <app-empty-state
              heading="No section patterns"
              message="No patterns match this review state."
            />
          } @else {
            <div class="analysis-pattern-grid">
              <div class="table-scroll">
                <table class="data-table">
                  <caption class="visually-hidden">
                    Independent normalized section patterns
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Section</th>
                      <th scope="col">Layout</th>
                      <th scope="col">Review</th>
                      <th scope="col">Duplicate</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (pattern of filteredPatterns(); track pattern.id) {
                      <tr
                        [class.selected-row]="selected()?.id === pattern.id"
                        (click)="selected.set(pattern)"
                      >
                        <th scope="row">
                          <button
                            class="table-link-button"
                            type="button"
                            (click)="selected.set(pattern)"
                          >
                            {{ pattern.section_type }}
                          </button>
                        </th>
                        <td>{{ pattern.layout }}</td>
                        <td>{{ pattern.approval_state }}</td>
                        <td>{{ pattern.duplicate_of_id ? 'Yes' : 'No' }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
              @if (selected(); as pattern) {
                <aside class="analysis-inspector" aria-labelledby="pattern-detail-heading">
                  <h3 id="pattern-detail-heading">{{ pattern.section_type }} pattern</h3>
                  <dl class="detail-list">
                    <div>
                      <dt>Purpose</dt>
                      <dd>{{ pattern.pattern.copy_purpose }}</dd>
                    </div>
                    <div>
                      <dt>Category</dt>
                      <dd>{{ pattern.category }}</dd>
                    </div>
                    <div>
                      <dt>Styles</dt>
                      <dd>{{ pattern.style_tags.join(', ') || 'None' }}</dd>
                    </div>
                    <div>
                      <dt>Confidence</dt>
                      <dd>{{ percent(pattern.confidence) }}</dd>
                    </div>
                    <div>
                      <dt>Pattern hash</dt>
                      <dd>
                        <code>{{ compactDigest(pattern.pattern_hash) }}</code>
                      </dd>
                    </div>
                  </dl>
                  <h4>Controlled components</h4>
                  <ul>
                    @for (component of pattern.pattern.components; track component.order) {
                      <li>
                        {{ component.component_name }} · {{ component.layout }} ·
                        {{ component.copy_purpose }}
                      </li>
                    }
                  </ul>
                  <h4>Retrieval document</h4>
                  <p class="retrieval-document">{{ pattern.retrieval_document }}</p>
                  <label class="form-field"
                    ><span class="field-label">Review note (optional)</span
                    ><textarea
                      class="text-input textarea-input"
                      maxlength="500"
                      [(ngModel)]="reviewNote"
                    ></textarea>
                  </label>
                  <div class="compact-actions">
                    <button
                      class="primary-button"
                      type="button"
                      (click)="curatePattern(pattern, 'approved')"
                    >
                      Approve</button
                    ><button
                      class="secondary-button"
                      type="button"
                      (click)="curatePattern(pattern, 'rejected')"
                    >
                      Reject</button
                    ><button
                      class="secondary-button"
                      type="button"
                      (click)="curatePattern(pattern, 'needs_review')"
                    >
                      Needs review
                    </button>
                  </div>
                </aside>
              }
            </div>
          }
        </section>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalysisReviewPageComponent {
  private readonly api = inject(AnalysisReviewApiService);
  private readonly notifications = inject(NotificationService);
  private readonly projectId = inject(ActivatedRoute).snapshot.paramMap.get('projectId') ?? '';
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly profiles = signal<readonly PageProfileResponse[]>([]);
  readonly patterns = signal<readonly SectionPatternResponse[]>([]);
  readonly selected = signal<SectionPatternResponse | null>(null);
  readonly filter = signal<'all' | ApprovalState>('all');
  readonly filteredPatterns = computed(() =>
    this.filter() === 'all'
      ? this.patterns()
      : this.patterns().filter((item) => item.approval_state === this.filter()),
  );
  reviewNote = '';

  constructor() {
    void this.load();
  }

  percent(value: number): string {
    return `${String(Math.round(value * 100))}%`;
  }
  compactDigest(value: string): string {
    return value.length > 16 ? `${value.slice(0, 12)}…` : value;
  }
  changeFilter(value: 'all' | ApprovalState): void {
    this.filter.set(value);
  }

  async curateProfile(profile: PageProfileResponse, state: ApprovalState): Promise<void> {
    try {
      const updated = await this.api.curatePage(this.projectId, profile, state, null);
      this.profiles.update((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
      this.notifications.success('Page profile review updated.');
    } catch (error: unknown) {
      this.notifications.error(messageFromError(error));
    }
  }

  async curatePattern(pattern: SectionPatternResponse, state: ApprovalState): Promise<void> {
    try {
      const note = this.reviewNote.trim() || null;
      const updated = await this.api.curatePattern(this.projectId, pattern, state, note);
      this.patterns.update((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
      this.selected.set(updated);
      this.notifications.success('Section pattern review updated.');
    } catch (error: unknown) {
      this.notifications.error(messageFromError(error));
    }
  }

  private async load(): Promise<void> {
    try {
      const [profiles, patterns] = await Promise.all([
        this.api.pageProfiles(this.projectId),
        this.api.sectionPatterns(this.projectId),
      ]);
      this.profiles.set(profiles.items);
      this.patterns.set(patterns.items);
      this.selected.set(patterns.items[0] ?? null);
    } catch (error: unknown) {
      this.error.set(messageFromError(error));
    } finally {
      this.loading.set(false);
    }
  }
}

function messageFromError(error: unknown): string {
  return typeof error === 'object' &&
    error !== null &&
    'message' in error &&
    typeof error.message === 'string'
    ? error.message
    : 'Analysis review could not be updated.';
}
