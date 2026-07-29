import { PercentPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import type { DatasetResponse, ProjectResponse } from '@platform/api-client';

import { DatasetApiService } from '../../core/datasets/dataset-api.service';
import { ProjectApiService } from '../../core/projects/project-api.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

interface DatasetListEntry {
  readonly dataset: DatasetResponse;
  readonly project: ProjectResponse;
}

@Component({
  imports: [PercentPipe, RouterLink, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="datasets-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Governed training and retrieval inputs</p>
          <h1 id="datasets-heading">Datasets</h1>
          <p>Versioned selections of approved, provenance-safe normalized patterns.</p>
        </div>
        @if (projectId(); as currentProjectId) {
          <a
            class="primary-button"
            [routerLink]="['/projects', currentProjectId, 'datasets', 'new']"
          >
            Create dataset
          </a>
        }
      </header>
      @if (loading()) {
        <app-loading-state label="Loading datasets…" />
      } @else if (error()) {
        <div class="state-card" role="alert">{{ error() }}</div>
      } @else if (entries().length === 0) {
        <app-empty-state
          heading="No datasets"
          message="Create a dataset through the API after approving normalized analysis patterns."
        />
      } @else {
        <div class="table-scroll">
          <table class="data-table">
            <caption class="visually-hidden">
              Project datasets
            </caption>
            <thead>
              <tr>
                <th scope="col">Dataset</th>
                <th scope="col">Project</th>
                <th scope="col">Purpose</th>
                <th scope="col">Policy</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              @for (entry of entries(); track entry.dataset.id) {
                <tr>
                  <th scope="row">
                    <a
                      [routerLink]="['/projects', entry.project.id, 'datasets', entry.dataset.id]"
                      >{{ entry.dataset.name }}</a
                    >
                  </th>
                  <td>{{ entry.project.name }}</td>
                  <td>{{ entry.dataset.purpose }}</td>
                  <td>
                    {{ entry.dataset.minimum_confidence | percent }} confidence ·
                    {{ entry.dataset.require_approved ? 'approved only' : 'reviewed and draft' }}
                  </td>
                  <td>
                    <span class="status-pill" [attr.data-state]="entry.dataset.status">{{
                      entry.dataset.status
                    }}</span>
                  </td>
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
export class DatasetListPageComponent {
  private readonly datasets = inject(DatasetApiService);
  private readonly projects = inject(ProjectApiService);
  private readonly route = inject(ActivatedRoute);
  readonly entries = signal<readonly DatasetListEntry[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const projectId = this.projectId();
      const projects =
        projectId === null
          ? (
              await this.projects.list({
                offset: 0,
                limit: 100,
                sort_by: 'updated_at',
                sort_order: 'desc',
              })
            ).items
          : [await this.projects.get(projectId)];
      const pages = await Promise.all(
        projects.map(async (project) => ({ project, page: await this.datasets.list(project.id) })),
      );
      this.entries.set(
        pages.flatMap(({ project, page }) => page.items.map((dataset) => ({ project, dataset }))),
      );
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Datasets could not be loaded.');
    } finally {
      this.loading.set(false);
    }
  }

  projectId(): string | null {
    for (const route of [...this.route.pathFromRoot].reverse()) {
      const value = route.snapshot.paramMap.get('projectId');
      if (value !== null) return value;
    }
    return null;
  }
}
