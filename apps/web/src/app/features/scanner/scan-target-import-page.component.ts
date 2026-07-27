import { HttpEventType } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import type { ScanTargetImportResponse } from '@platform/api-client';

import { ScanTargetImportApiService } from '../../core/scans/scan-target-import-api.service';
import { NotificationService } from '../../core/notifications/notification.service';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_FILE_BYTES = 20 * 1024 * 1024;

@Component({
  imports: [ReactiveFormsModule],
  template: `
    <section class="page-stack" aria-labelledby="target-import-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Scanner · target intake</p>
          <h1 id="target-import-heading">Import authorized scan targets</h1>
          <p>
            Validate up to 50,000 domains without making network requests. Review the dry-run
            summary before adding accepted targets to the campaign.
          </p>
        </div>
      </header>

      <form class="surface-card form-stack" [formGroup]="form" (ngSubmit)="validateImport()">
        <div class="responsive-form-grid">
          <label class="form-field">
            <span class="field-label">Project ID</span>
            <input class="text-input" formControlName="projectId" autocomplete="off" />
          </label>
          <label class="form-field">
            <span class="field-label">Campaign ID</span>
            <input class="text-input" formControlName="campaignId" autocomplete="off" />
          </label>
        </div>

        <fieldset class="choice-group">
          <legend class="field-label">Import source</legend>
          <label><input type="radio" formControlName="mode" value="paste" /> Paste domains</label>
          <label
            ><input type="radio" formControlName="mode" value="file" /> Upload TXT or CSV</label
          >
        </fieldset>

        @if (form.controls.mode.value === 'paste') {
          <label class="form-field">
            <span class="field-label">Domains or HTTP(S) URLs</span>
            <textarea
              class="text-input code-input target-paste"
              formControlName="pastedTargets"
              placeholder="example.com&#10;https://docs.example.org/path"
            ></textarea>
            <span class="field-hint"
              >One target per line. Paths are normalized to domain roots.</span
            >
          </label>
        } @else {
          <label class="form-field">
            <span class="field-label">TXT or CSV file</span>
            <input
              class="file-input"
              type="file"
              accept=".csv,.txt,text/csv,text/plain"
              (change)="selectFile($event)"
            />
            <span class="field-hint">
              CSV accepts domain, url, hostname, or website as the target column; other columns are
              preserved as metadata.
            </span>
          </label>
        }

        <label class="attestation-field">
          <input type="checkbox" formControlName="authorizationAttested" />
          <span>
            I attest that I am authorized to crawl every submitted target and will honor source
            policies and applicable law.
          </span>
        </label>

        @if (errorMessage()) {
          <p class="field-error" role="alert">{{ errorMessage() }}</p>
        }

        <div class="button-row">
          <button class="primary-button" type="submit" [disabled]="!canValidate()">
            {{ busy() ? 'Validating…' : 'Run dry-run validation' }}
          </button>
        </div>

        @if (busy()) {
          <div class="upload-progress" aria-live="polite">
            <progress max="100" [value]="progress()"></progress>
            <span>{{ progress() }}% uploaded</span>
          </div>
        }
      </form>

      @if (result(); as summary) {
        <section class="surface-card page-stack" aria-labelledby="import-summary-heading">
          <div>
            <p class="eyebrow">{{ summary.status }}</p>
            <h2 id="import-summary-heading">Import summary</h2>
            <p>{{ summary.processed_rows }} rows processed. Row numbers are retained for review.</p>
          </div>
          <dl class="summary-grid">
            @for (item of summaryItems(summary); track item.label) {
              <div>
                <dt>{{ item.label }}</dt>
                <dd>{{ item.value }}</dd>
              </div>
            }
          </dl>
          <div class="button-row">
            @if (summary.status === 'completed') {
              <button
                class="primary-button"
                type="button"
                [disabled]="busy() || !form.controls.authorizationAttested.value"
                (click)="commitImport()"
              >
                Commit {{ summary.accepted_count }} accepted targets
              </button>
            }
            @if (
              summary.invalid_count +
                summary.blocked_count +
                summary.duplicate_count +
                summary.already_present_count >
              0
            ) {
              <button class="secondary-button" type="button" (click)="downloadErrors()">
                Download CSV errors
              </button>
            }
          </div>
        </section>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScanTargetImportPageComponent {
  private readonly api = inject(ScanTargetImportApiService);
  private readonly notifications = inject(NotificationService);
  private readonly route = inject(ActivatedRoute);
  private readonly file = signal<File | null>(null);

  readonly busy = signal(false);
  readonly progress = signal(0);
  readonly result = signal<ScanTargetImportResponse | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly form = new FormGroup({
    projectId: new FormControl(this.routeParam('projectId'), {
      nonNullable: true,
      validators: [Validators.required, Validators.pattern(UUID_PATTERN)],
    }),
    campaignId: new FormControl(this.routeParam('campaignId'), {
      nonNullable: true,
      validators: [Validators.required, Validators.pattern(UUID_PATTERN)],
    }),
    mode: new FormControl<'paste' | 'file'>('paste', { nonNullable: true }),
    pastedTargets: new FormControl('', { nonNullable: true }),
    authorizationAttested: new FormControl(false, {
      nonNullable: true,
      validators: [Validators.requiredTrue],
    }),
  });
  readonly canValidate = computed(
    () =>
      !this.busy() &&
      this.form.valid &&
      (this.form.controls.mode.value === 'paste'
        ? this.form.controls.pastedTargets.value.trim().length > 0
        : this.file() !== null),
  );

  selectFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const selected = input.files?.item(0) ?? null;
    if (selected !== null && selected.size > MAX_FILE_BYTES) {
      input.value = '';
      this.file.set(null);
      this.errorMessage.set('The file exceeds the 20 MiB upload limit.');
      return;
    }
    this.file.set(selected);
    this.errorMessage.set(null);
  }

  validateImport(): void {
    if (!this.canValidate()) {
      this.form.markAllAsTouched();
      return;
    }
    const mode = this.form.controls.mode.value;
    const selected = this.file();
    const body =
      mode === 'paste'
        ? new Blob([this.form.controls.pastedTargets.value], { type: 'text/plain' })
        : selected;
    if (body === null) return;
    const sourceType =
      mode === 'paste' ? 'paste' : selected?.name.toLowerCase().endsWith('.csv') ? 'csv' : 'text';
    this.busy.set(true);
    this.progress.set(0);
    this.result.set(null);
    this.errorMessage.set(null);
    this.api
      .upload({
        projectId: this.form.controls.projectId.value,
        campaignId: this.form.controls.campaignId.value,
        body,
        sourceType,
        filename: selected?.name,
        dryRun: true,
        authorizationAttested: this.form.controls.authorizationAttested.value,
      })
      .subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress && event.total !== undefined) {
            this.progress.set(Math.round((event.loaded / event.total) * 100));
          }
          if (event.type === HttpEventType.Response) {
            this.progress.set(100);
            this.result.set(event.body);
          }
        },
        error: (error: unknown) => {
          this.busy.set(false);
          this.errorMessage.set(messageFromError(error));
        },
        complete: () => {
          this.busy.set(false);
        },
      });
  }

  async commitImport(): Promise<void> {
    const current = this.result();
    if (current?.status !== 'completed') return;
    this.busy.set(true);
    this.errorMessage.set(null);
    try {
      this.result.set(
        await this.api.commit(
          this.form.controls.projectId.value,
          this.form.controls.campaignId.value,
          current,
        ),
      );
      this.notifications.success('Accepted targets were added to the campaign.');
    } catch (error: unknown) {
      this.errorMessage.set(messageFromError(error));
    } finally {
      this.busy.set(false);
    }
  }

  downloadErrors(): void {
    const current = this.result();
    if (current === null) return;
    this.api
      .downloadErrors(
        this.form.controls.projectId.value,
        this.form.controls.campaignId.value,
        current.id,
      )
      .subscribe((blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `scan-target-import-${current.id}-errors.csv`;
        link.click();
        URL.revokeObjectURL(url);
      });
  }

  summaryItems(summary: ScanTargetImportResponse) {
    return [
      { label: 'Accepted', value: summary.accepted_count },
      { label: 'Duplicates', value: summary.duplicate_count },
      { label: 'Invalid', value: summary.invalid_count },
      { label: 'Blocked', value: summary.blocked_count },
      { label: 'Already present', value: summary.already_present_count },
      { label: 'Committed', value: summary.committed_count },
    ] as const;
  }

  private routeParam(name: string): string {
    for (const route of [...this.route.pathFromRoot].reverse()) {
      const value = route.snapshot.paramMap.get(name);
      if (value !== null) return value;
    }
    return '';
  }
}

function messageFromError(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return 'Target validation could not be completed.';
}
