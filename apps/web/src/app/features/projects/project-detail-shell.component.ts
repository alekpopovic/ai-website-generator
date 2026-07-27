import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import type { ProjectResponse } from '@platform/api-client';

import { ProjectApiService } from '../../core/projects/project-api.service';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [RouterLink, RouterLinkActive, RouterOutlet, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="project-heading">
      @if (loading()) {
        <app-loading-state label="Loading project…" />
      } @else if (project(); as current) {
        <header class="page-header project-detail-header">
          <div>
            <p class="eyebrow">Project · {{ current.status }}</p>
            <h1 id="project-heading">{{ current.name }}</h1>
            <p>{{ current.description || 'No description provided.' }}</p>
          </div>
          <a class="secondary-button" [routerLink]="['/projects', current.id, 'edit']"
            >Edit project</a
          >
        </header>
        <nav class="project-tabs" aria-label="Project sections">
          @for (tab of tabs; track tab.path) {
            <a [routerLink]="tab.path" routerLinkActive="project-tab-active">{{ tab.label }}</a>
          }
        </nav>
        <router-outlet />
      } @else {
        <div class="state-card" role="alert">{{ errorMessage() }}</div>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectDetailShellComponent {
  private readonly api = inject(ProjectApiService);
  private readonly projectId = inject(ActivatedRoute).snapshot.paramMap.get('projectId');
  readonly project = signal<ProjectResponse | null>(null);
  readonly loading = signal(true);
  readonly errorMessage = signal('Project could not be loaded.');
  readonly tabs = [
    { label: 'Generated sites', path: 'generated-sites' },
    { label: 'Scans', path: 'scans' },
    { label: 'Datasets', path: 'datasets' },
    { label: 'Assets', path: 'assets' },
    { label: 'Settings', path: 'settings' },
  ] as const;

  constructor() {
    if (this.projectId !== null) void this.load(this.projectId);
  }

  private async load(projectId: string): Promise<void> {
    try {
      this.project.set(await this.api.get(projectId));
    } catch (error: unknown) {
      this.errorMessage.set(messageFromError(error));
    } finally {
      this.loading.set(false);
    }
  }
}

function messageFromError(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return 'Project could not be loaded.';
}
