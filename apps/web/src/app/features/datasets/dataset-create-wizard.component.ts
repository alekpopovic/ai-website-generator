import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { DatasetApiService } from '../../core/datasets/dataset-api.service';

@Component({
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <section class="page-stack narrow-page" aria-labelledby="create-dataset-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Dataset curation</p>
          <h1 id="create-dataset-heading">Create dataset</h1>
          <p>
            Define a reusable selection policy. You can review matching patterns before sealing.
          </p>
        </div>
      </header>

      <nav aria-label="Creation progress">
        <ol class="wizard-steps">
          <li [attr.aria-current]="step() === 1 ? 'step' : null">1. Purpose</li>
          <li [attr.aria-current]="step() === 2 ? 'step' : null">2. Selection</li>
          <li [attr.aria-current]="step() === 3 ? 'step' : null">3. Review</li>
        </ol>
      </nav>

      <form class="surface-card page-stack" [formGroup]="form" (ngSubmit)="submit()">
        @if (step() === 1) {
          <fieldset class="form-stack">
            <legend>Dataset purpose</legend>
            <label>Name <input formControlName="name" autocomplete="off" /></label>
            <label>Purpose <textarea formControlName="purpose" rows="3"></textarea></label>
            <label>Description <textarea formControlName="description" rows="4"></textarea></label>
          </fieldset>
        } @else if (step() === 2) {
          <fieldset class="form-stack">
            <legend>Pattern selection</legend>
            <label>
              Minimum confidence
              <input
                formControlName="minimumConfidence"
                type="number"
                min="0"
                max="1"
                step="0.05"
              />
            </label>
            <label>
              Categories
              <input formControlName="categories" placeholder="homepage, pricing" />
              <small>Comma-separated controlled categories.</small>
            </label>
            <label>
              Languages
              <input formControlName="languages" placeholder="en, de" />
            </label>
            <label class="checkbox-label">
              <input formControlName="requireApproved" type="checkbox" />
              Include approved patterns only
            </label>
            <label>
              Provenance requirement
              <select formControlName="provenance">
                <option value="authorized">Authorized only</option>
                <option value="restricted">Restricted</option>
              </select>
            </label>
          </fieldset>
        } @else {
          <section aria-labelledby="review-heading">
            <h2 id="review-heading">Review policy</h2>
            <dl class="summary-grid">
              <div>
                <dt>Name</dt>
                <dd>{{ form.controls.name.value }}</dd>
              </div>
              <div>
                <dt>Purpose</dt>
                <dd>{{ form.controls.purpose.value }}</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>{{ form.controls.minimumConfidence.value }}</dd>
              </div>
              <div>
                <dt>Approval</dt>
                <dd>{{ form.controls.requireApproved.value ? 'Required' : 'Optional' }}</dd>
              </div>
              <div>
                <dt>Categories</dt>
                <dd>{{ form.controls.categories.value || 'All' }}</dd>
              </div>
              <div>
                <dt>Languages</dt>
                <dd>{{ form.controls.languages.value || 'All' }}</dd>
              </div>
            </dl>
          </section>
        }

        @if (error()) {
          <p class="field-error" role="alert">{{ error() }}</p>
        }
        <div class="button-row">
          @if (step() > 1) {
            <button type="button" class="secondary-button" (click)="previous()">Back</button>
          } @else {
            <a class="secondary-button" routerLink="..">Cancel</a>
          }
          @if (step() < 3) {
            <button type="button" class="primary-button" (click)="next()">Continue</button>
          } @else {
            <button type="submit" class="primary-button" [disabled]="saving()">
              {{ saving() ? 'Creating…' : 'Create dataset and draft' }}
            </button>
          }
        </div>
      </form>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DatasetCreateWizardComponent {
  private readonly api = inject(DatasetApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly projectId = this.route.snapshot.paramMap.get('projectId') ?? '';
  readonly step = signal(1);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly form = inject(FormBuilder).nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(200)]],
    purpose: ['', [Validators.required, Validators.maxLength(500)]],
    description: ['', Validators.maxLength(2000)],
    minimumConfidence: [0.7, [Validators.required, Validators.min(0), Validators.max(1)]],
    categories: [''],
    languages: [''],
    requireApproved: [true],
    provenance: new FormControl<'authorized' | 'restricted'>('authorized', { nonNullable: true }),
  });

  next(): void {
    if (this.step() === 1) {
      this.form.controls.name.markAsTouched();
      this.form.controls.purpose.markAsTouched();
      if (this.form.controls.name.invalid || this.form.controls.purpose.invalid) return;
    }
    this.step.update((value) => Math.min(3, value + 1));
  }

  previous(): void {
    this.step.update((value) => Math.max(1, value - 1));
  }

  async submit(): Promise<void> {
    if (this.form.invalid || this.saving()) {
      this.form.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    const value = this.form.getRawValue();
    try {
      const dataset = await this.api.create(this.projectId, {
        name: value.name.trim(),
        purpose: value.purpose.trim(),
        description: value.description.trim() || null,
        source_campaign_filters: [],
        category_filters: splitValues(value.categories),
        language_filters: splitValues(value.languages),
        item_types: ['section_pattern'],
        minimum_confidence: value.minimumConfidence,
        require_approved: value.requireApproved,
        provenance_requirements: [value.provenance],
      });
      const version = await this.api.createVersion(this.projectId, dataset.id);
      await this.router.navigate(['../', dataset.id, 'versions', version.id], {
        relativeTo: this.route,
      });
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'The dataset could not be created.');
    } finally {
      this.saving.set(false);
    }
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
