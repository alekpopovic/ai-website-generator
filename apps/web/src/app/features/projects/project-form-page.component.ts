import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import type {
  JsonValueInput,
  ProjectCreateRequest,
  ProjectUpdateRequest,
} from '@platform/api-client';

import { ProjectApiService } from '../../core/projects/project-api.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { FormFieldComponent } from '../../shared/forms/form-field.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [ReactiveFormsModule, RouterLink, FormFieldComponent, LoadingStateComponent],
  template: `
    <section class="page-stack narrow-page" aria-labelledby="project-form-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Project</p>
          <h1 id="project-form-heading">{{ editing ? 'Edit project' : 'Create project' }}</h1>
          <p>Define the workspace defaults used by later scans and generations.</p>
        </div>
      </header>
      @if (loading()) {
        <app-loading-state label="Loading project…" />
      } @else {
        <form class="form-card form-stack" [formGroup]="form" (ngSubmit)="submit()" novalidate>
          <app-form-field label="Name" controlId="project-name" [error]="fieldError('name')">
            <input id="project-name" class="text-input" formControlName="name" autocomplete="off" />
          </app-form-field>
          <app-form-field
            label="Slug"
            controlId="project-slug"
            hint="Leave blank to generate it from the name."
            [error]="fieldError('slug')"
          >
            <input id="project-slug" class="text-input" formControlName="slug" autocomplete="off" />
          </app-form-field>
          <app-form-field
            label="Description"
            controlId="project-description"
            [error]="fieldError('description')"
          >
            <textarea
              id="project-description"
              class="text-input textarea-input"
              formControlName="description"
            ></textarea>
          </app-form-field>
          <div class="form-columns">
            <app-form-field
              label="Default language"
              controlId="project-language"
              [error]="fieldError('defaultLanguage')"
            >
              <input
                id="project-language"
                class="text-input"
                formControlName="defaultLanguage"
                placeholder="en"
              />
            </app-form-field>
            <app-form-field
              label="Default industry"
              controlId="project-industry"
              [error]="fieldError('defaultIndustry')"
            >
              <input id="project-industry" class="text-input" formControlName="defaultIndustry" />
            </app-form-field>
          </div>
          <app-form-field
            label="Settings JSON"
            controlId="project-settings"
            hint="A JSON object containing project-specific defaults."
            [error]="fieldError('settings')"
          >
            <textarea
              id="project-settings"
              class="text-input code-input"
              formControlName="settings"
              spellcheck="false"
            ></textarea>
          </app-form-field>
          @if (formError()) {
            <p class="field-error" role="alert">{{ formError() }}</p>
          }
          <div class="form-actions">
            <button class="primary-button" type="submit" [disabled]="submitting()">
              {{ submitting() ? 'Saving…' : 'Save project' }}
            </button>
            <a class="secondary-button" [routerLink]="cancelUrl">Cancel</a>
          </div>
        </form>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectFormPageComponent {
  private readonly api = inject(ProjectApiService);
  private readonly notifications = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly formBuilder = inject(FormBuilder);
  readonly projectId = inject(ActivatedRoute).snapshot.paramMap.get('projectId');
  readonly editing = this.projectId !== null;
  readonly loading = signal(this.editing);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);
  private version: number | null = null;
  readonly form = this.formBuilder.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(200)]],
    slug: ['', [Validators.pattern(/^[a-z0-9]+(?:-[a-z0-9]+)*$/), Validators.maxLength(100)]],
    description: ['', [Validators.maxLength(2000)]],
    defaultLanguage: ['en', [Validators.required, Validators.maxLength(35)]],
    defaultIndustry: ['', [Validators.maxLength(100)]],
    settings: ['{}', [Validators.required]],
  });

  constructor() {
    if (this.projectId !== null) void this.load(this.projectId);
  }

  get cancelUrl(): readonly string[] {
    return this.projectId === null ? ['/projects'] : ['/projects', this.projectId];
  }

  fieldError(name: keyof typeof this.form.controls): string | null {
    const control = this.form.controls[name];
    if (!control.touched || control.valid) return null;
    const server: unknown = control.getError('server');
    if (typeof server === 'string') return server;
    if (control.hasError('required')) return 'This field is required.';
    if (control.hasError('pattern')) return 'Use lowercase letters, numbers, and single hyphens.';
    if (control.hasError('json')) return 'Enter a valid JSON object.';
    return 'This value is too long.';
  }

  async submit(): Promise<void> {
    this.form.markAllAsTouched();
    let settings: Record<string, JsonValueInput>;
    try {
      settings = parseProjectSettings(this.form.controls.settings.value);
    } catch {
      this.form.controls.settings.setErrors({ json: true });
      return;
    }
    if (this.form.invalid || this.submitting()) return;
    this.submitting.set(true);
    this.formError.set(null);
    const value = this.form.getRawValue();
    const common = {
      name: value.name,
      description: value.description.trim() || null,
      default_language: value.defaultLanguage,
      default_industry: value.defaultIndustry.trim() || null,
      settings,
    };
    try {
      const project =
        this.projectId === null
          ? await this.api.create({
              ...common,
              ...(value.slug ? { slug: value.slug } : {}),
            } satisfies ProjectCreateRequest)
          : await this.api.update(this.projectId, {
              ...common,
              slug: value.slug,
              version: this.requiredVersion(),
            } satisfies ProjectUpdateRequest);
      this.notifications.success(this.editing ? 'Project updated.' : 'Project created.');
      await this.router.navigate(['/projects', project.id]);
    } catch (error: unknown) {
      this.applyProblemFields(error);
      this.formError.set(messageFromError(error));
    } finally {
      this.submitting.set(false);
    }
  }

  private async load(projectId: string): Promise<void> {
    try {
      const project = await this.api.get(projectId);
      this.version = project.version;
      this.form.setValue({
        name: project.name,
        slug: project.slug,
        description: project.description ?? '',
        defaultLanguage: project.default_language,
        defaultIndustry: project.default_industry ?? '',
        settings: JSON.stringify(project.settings, null, 2),
      });
    } catch (error: unknown) {
      this.formError.set(messageFromError(error));
    } finally {
      this.loading.set(false);
    }
  }

  private requiredVersion(): number {
    if (this.version === null) throw new Error('Project version is unavailable.');
    return this.version;
  }

  private applyProblemFields(error: unknown): void {
    if (typeof error !== 'object' || error === null || !('problem' in error)) return;
    const problem = (
      error as { problem?: { invalid_parameters?: { name: string; reason: string }[] } }
    ).problem;
    const fields: Record<string, keyof typeof this.form.controls> = {
      name: 'name',
      slug: 'slug',
      description: 'description',
      default_language: 'defaultLanguage',
      default_industry: 'defaultIndustry',
      settings: 'settings',
    };
    for (const invalid of problem?.invalid_parameters ?? []) {
      const control = fields[invalid.name];
      if (control !== undefined) this.form.controls[control].setErrors({ server: invalid.reason });
    }
  }
}

export function parseProjectSettings(value: string): Record<string, JsonValueInput> {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('Settings must be a JSON object.');
  }
  return parsed as Record<string, JsonValueInput>;
}

function messageFromError(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return 'The project could not be saved.';
}
