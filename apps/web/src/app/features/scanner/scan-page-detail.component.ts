import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type {
  CrawlPageDetailResponse,
  CrawlPageResponse,
  ScanArtifactResponse,
} from '@platform/api-client';

import { NotificationService } from '../../core/notifications/notification.service';
import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [JsonPipe, ReactiveFormsModule, RouterLink, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="page-detail-heading">
      <a routerLink="..">← Back to pages</a>
      @if (loading()) {
        <app-loading-state label="Loading page scan…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (detail(); as result) {
        <header class="page-header">
          <div>
            <p class="eyebrow">{{ result.page.page_type || 'Unclassified' }}</p>
            <h2 id="page-detail-heading">{{ result.page.title || result.page.normalized_url }}</h2>
            <p class="safe-url">{{ result.page.normalized_url }}</p>
          </div>
          <span class="status-pill" [attr.data-state]="result.page.status">{{
            result.page.status
          }}</span>
        </header>
        <section class="screenshot-grid" aria-label="Captured screenshots">
          @for (viewport of ['desktop', 'mobile']; track viewport) {
            <figure class="surface-card screenshot-card">
              <figcaption>{{ viewport }} screenshot</figcaption>
              @if (screenshot(viewport); as url) {
                <img
                  [src]="url"
                  [alt]="
                    viewport + ' screenshot of ' + (result.page.title || result.page.normalized_url)
                  "
                />
              } @else {
                <p>No {{ viewport }} screenshot is available.</p>
              }
            </figure>
          }
        </section>
        <div class="review-grid">
          <section class="surface-card">
            <h3>Classification</h3>
            <dl class="metadata-list">
              <div>
                <dt>Page type</dt>
                <dd>{{ result.page.page_type || 'Unknown' }}</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>{{ result.page.page_type_score ?? 'Not scored' }}</dd>
              </div>
              <div>
                <dt>Classifier</dt>
                <dd>{{ result.page.classifier || 'Not classified' }}</dd>
              </div>
            </dl>
            <ul>
              @for (reason of result.page.classification_explanation; track reason) {
                <li>{{ reason }}</li>
              }
            </ul>
          </section>
          <section class="surface-card">
            <h3>Fingerprint groups</h3>
            <dl class="metadata-list">
              <div>
                <dt>Exact group</dt>
                <dd>{{ result.page.exact_group_key || 'None' }}</dd>
              </div>
              <div>
                <dt>Near group</dt>
                <dd>{{ result.page.near_group_key || 'None' }}</dd>
              </div>
              <div>
                <dt>Template group</dt>
                <dd>{{ result.page.template_group_key || 'None' }}</dd>
              </div>
            </dl>
          </section>
          <section class="surface-card">
            <h3>Extracted metadata</h3>
            <dl class="metadata-list">
              <div>
                <dt>Final URL</dt>
                <dd class="safe-url">{{ result.page.final_url || 'Unavailable' }}</dd>
              </div>
              <div>
                <dt>Title</dt>
                <dd>{{ result.page.title || 'Unavailable' }}</dd>
              </div>
              <div>
                <dt>Description</dt>
                <dd>{{ result.page.meta_description || 'Unavailable' }}</dd>
              </div>
              <div>
                <dt>Language</dt>
                <dd>{{ result.page.language || 'Unknown' }}</dd>
              </div>
              <div>
                <dt>Content type</dt>
                <dd>{{ result.page.content_type || 'Unknown' }}</dd>
              </div>
            </dl>
          </section>
          <section class="surface-card">
            <h3>Representative selection</h3>
            <p>
              {{ result.page.representative_selected ? 'Selected' : 'Not selected' }} · score
              {{ result.page.representative_score ?? 'not scored' }}
            </p>
            <ul>
              @for (reason of result.page.selection_explanation; track reason) {
                <li>{{ reason }}</li>
              }
            </ul>
            <label class="form-field"
              ><span class="field-label">Manual reason</span
              ><input class="text-input" [formControl]="reason"
            /></label>
            <div class="button-row">
              <button
                class="secondary-button"
                type="button"
                (click)="override(result.page, 'include')"
              >
                Include</button
              ><button
                class="secondary-button"
                type="button"
                (click)="override(result.page, 'exclude')"
              >
                Exclude</button
              ><button
                class="secondary-button"
                type="button"
                (click)="override(result.page, 'automatic')"
              >
                Use automatic
              </button>
            </div>
          </section>
        </div>
        <section class="surface-card">
          <h3>Console diagnostics</h3>
          @if (consoleErrors(result).length === 0) {
            <p>No console or page errors were recorded.</p>
          } @else {
            <ul class="diagnostic-list">
              @for (item of consoleErrors(result); track $index) {
                <li>
                  <pre>{{ item | json }}</pre>
                </li>
              }
            </ul>
          }
        </section>
        <section class="surface-card">
          <h3>Artifact manifest</h3>
          <p>Metadata only; private object keys and credentials are not exposed.</p>
          <div class="table-scroll">
            <table class="data-table">
              <thead>
                <tr>
                  <th scope="col">Artifact</th>
                  <th scope="col">Viewport</th>
                  <th scope="col">Size</th>
                  <th scope="col">Retention</th>
                </tr>
              </thead>
              <tbody>
                @for (artifact of result.artifacts; track artifact.id) {
                  <tr>
                    <th scope="row">{{ artifact.artifact_type }}</th>
                    <td>{{ artifact.viewport || 'All' }}</td>
                    <td>{{ artifact.size_bytes }} bytes</td>
                    <td>{{ artifact.retention_status }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanPageDetailComponent {
  private readonly api = inject(ScanReviewApiService);
  private readonly notifications = inject(NotificationService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  readonly detail = signal<CrawlPageDetailResponse | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly reason = new FormControl('', { nonNullable: true });
  private readonly screenshots = signal<Readonly<Record<string, string>>>({});
  private readonly projectId = this.param('projectId');
  private readonly campaignId = this.param('campaignId');
  private readonly pageId = this.param('pageId');
  constructor() {
    this.destroyRef.onDestroy(() => {
      for (const url of Object.values(this.screenshots())) URL.revokeObjectURL(url);
    });
    void this.load();
  }
  screenshot(viewport: string): string | undefined {
    return this.screenshots()[viewport];
  }
  consoleErrors(result: CrawlPageDetailResponse): unknown[] {
    return result.page_scans.flatMap((scan) => [...scan.console_errors, ...scan.page_errors]);
  }
  async override(
    page: CrawlPageResponse,
    selection: 'automatic' | 'exclude' | 'include',
  ): Promise<void> {
    try {
      const updated = await this.api.overrideRepresentative(
        this.projectId,
        this.campaignId,
        page,
        selection,
        this.reason.value,
      );
      this.detail.update((current) => (current ? { ...current, page: updated } : current));
      this.notifications.success('Representative selection updated.');
    } catch (error: unknown) {
      this.notifications.error(
        error instanceof Error ? error.message : 'Selection could not be updated.',
      );
    }
  }
  private async load(): Promise<void> {
    try {
      const detail = await this.api.page(this.projectId, this.campaignId, this.pageId);
      this.detail.set(detail);
      await this.loadScreenshots(detail.artifacts);
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Page scan could not be loaded.');
    } finally {
      this.loading.set(false);
    }
  }
  private async loadScreenshots(artifacts: readonly ScanArtifactResponse[]): Promise<void> {
    const selected = artifacts.filter(
      (artifact) =>
        artifact.artifact_type === 'desktop_screenshot' ||
        artifact.artifact_type === 'mobile_screenshot',
    );
    const entries = await Promise.all(
      selected.map(
        async (artifact) =>
          [
            artifact.viewport ?? artifact.artifact_type.replace('_screenshot', ''),
            URL.createObjectURL(
              await this.api.screenshot(this.projectId, this.campaignId, artifact.id),
            ),
          ] as const,
      ),
    );
    this.screenshots.set(Object.fromEntries(entries));
  }
  private param(name: string): string {
    for (const route of [...this.route.pathFromRoot].reverse()) {
      const value = route.snapshot.paramMap.get(name);
      if (value) return value;
    }
    return '';
  }
}
