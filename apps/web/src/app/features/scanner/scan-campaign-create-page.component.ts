import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ScanReviewApiService } from '../../core/scans/scan-review-api.service';

@Component({
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <section class="page-stack narrow-page" aria-labelledby="create-campaign-heading">
      <header>
        <p class="eyebrow">Scanner · step {{ step() }} of 3</p>
        <h1 id="create-campaign-heading">Create scan campaign</h1>
        <p>Configure bounded discovery and attest authorization before any workflow can start.</p>
      </header>
      <ol class="wizard-steps" aria-label="Campaign creation progress">
        <li [attr.aria-current]="step() === 1 ? 'step' : null">Basics</li>
        <li [attr.aria-current]="step() === 2 ? 'step' : null">Limits</li>
        <li [attr.aria-current]="step() === 3 ? 'step' : null">Authorization</li>
      </ol>
      <form class="surface-card form-stack" [formGroup]="form" (ngSubmit)="submit()">
        @if (step() === 1) {
          <label class="form-field"
            ><span class="field-label">Campaign name</span
            ><input class="text-input" formControlName="name"
          /></label>
          <label class="form-field"
            ><span class="field-label">Include URL patterns</span
            ><textarea
              class="text-input textarea-input"
              formControlName="includePatterns"
            ></textarea
            ><span class="field-hint">One bounded glob per line.</span></label
          >
          <label class="form-field"
            ><span class="field-label">Exclude URL patterns</span
            ><textarea
              class="text-input textarea-input"
              formControlName="excludePatterns"
            ></textarea>
          </label>
        } @else if (step() === 2) {
          <div class="responsive-form-grid">
            <label class="form-field"
              ><span class="field-label">Maximum discovered pages per domain</span
              ><input class="text-input" type="number" formControlName="maxPages"
            /></label>
            <label class="form-field"
              ><span class="field-label">Maximum visual pages per domain</span
              ><input class="text-input" type="number" formControlName="maxVisualPages"
            /></label>
            <label class="form-field"
              ><span class="field-label">Maximum crawl depth</span
              ><input class="text-input" type="number" formControlName="maxDepth"
            /></label>
            <label class="form-field"
              ><span class="field-label">Crawl delay in seconds</span
              ><input class="text-input" type="number" step="0.5" formControlName="crawlDelay"
            /></label>
          </div>
          <label class="attestation-field"
            ><input type="checkbox" formControlName="storeRawHtml" /><span
              >Retain compressed raw response HTML. This remains restricted and is not shown in the
              normal UI.</span
            ></label
          >
        } @else {
          <div class="review-panel">
            <h2>Review</h2>
            <p>
              {{ form.controls.name.value }} · up to {{ form.controls.maxPages.value }} discovered
              and {{ form.controls.maxVisualPages.value }} visual pages per domain.
            </p>
            <p>robots.txt compliance is always enabled.</p>
          </div>
          <label class="attestation-field"
            ><input type="checkbox" formControlName="authorized" /><span
              >I attest that I am authorized to crawl all targets that will be added to this
              campaign.</span
            ></label
          >
        }
        @if (error()) {
          <p class="field-error" role="alert">{{ error() }}</p>
        }
        <div class="button-row">
          @if (step() > 1) {
            <button class="secondary-button" type="button" (click)="step.set(step() - 1)">
              Back
            </button>
          }
          @if (step() < 3) {
            <button class="primary-button" type="button" (click)="next()">Continue</button>
          } @else {
            <button
              class="primary-button"
              type="submit"
              [disabled]="saving() || !form.controls.authorized.value"
            >
              {{ saving() ? 'Creating…' : 'Create and import targets' }}
            </button>
          }
          <a class="secondary-button" routerLink="..">Cancel</a>
        </div>
      </form>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanCampaignCreatePageComponent {
  private readonly api = inject(ScanReviewApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly formBuilder = inject(FormBuilder);
  readonly step = signal(1);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly form = this.formBuilder.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(200)]],
    includePatterns: '',
    excludePatterns: '',
    maxPages: [100, [Validators.required, Validators.min(1), Validators.max(10_000)]],
    maxVisualPages: [20, [Validators.required, Validators.min(0), Validators.max(1_000)]],
    maxDepth: [5, [Validators.required, Validators.min(0), Validators.max(20)]],
    crawlDelay: [1, [Validators.required, Validators.min(0), Validators.max(60)]],
    storeRawHtml: false,
    authorized: [false, Validators.requiredTrue],
  });
  private readonly projectId = this.route.snapshot.paramMap.get('projectId') ?? '';

  next(): void {
    if (this.step() === 1 && this.form.controls.name.invalid) {
      this.form.controls.name.markAsTouched();
      return;
    }
    if (
      this.step() === 2 &&
      [
        this.form.controls.maxPages,
        this.form.controls.maxVisualPages,
        this.form.controls.maxDepth,
        this.form.controls.crawlDelay,
      ].some((control) => control.invalid)
    )
      return;
    this.step.update((value) => Math.min(3, value + 1));
  }

  async submit(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    const value = this.form.getRawValue();
    try {
      const campaign = await this.api.create(this.projectId, {
        name: value.name.trim(),
        authorization_attested_at: new Date().toISOString(),
        max_discovered_pages_per_domain: value.maxPages,
        max_visual_pages_per_domain: value.maxVisualPages,
        maximum_crawl_depth: value.maxDepth,
        crawl_delay_seconds: value.crawlDelay,
        include_url_patterns: lines(value.includePatterns),
        exclude_url_patterns: lines(value.excludePatterns),
        store_raw_html: value.storeRawHtml,
        respect_robots_txt: true,
      });
      await this.router.navigate(['..', campaign.id, 'import-targets'], { relativeTo: this.route });
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Campaign could not be created.');
    } finally {
      this.saving.set(false);
    }
  }
}

function lines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}
