import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import type { ListProjectsData, ProjectResponse } from '@platform/api-client';

import { ProjectApiService } from '../../core/projects/project-api.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { EmptyStateComponent } from '../../shared/states/empty-state.component';
import { LoadingStateComponent } from '../../shared/states/loading-state.component';

@Component({
  imports: [ReactiveFormsModule, RouterLink, EmptyStateComponent, LoadingStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="projects-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Workspace</p>
          <h1 id="projects-heading">Projects</h1>
          <p>Create and manage your website-generation workspaces.</p>
        </div>
        <a class="primary-button" routerLink="/projects/new">Create project</a>
      </header>

      <form class="filter-bar" [formGroup]="filters" (ngSubmit)="applyFilters()">
        <label>
          <span>Search</span>
          <input class="text-input" type="search" formControlName="search" />
        </label>
        <label>
          <span>Status</span>
          <select class="text-input" formControlName="status">
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
        </label>
        <label>
          <span>Sort</span>
          <select class="text-input" formControlName="sortBy">
            <option value="updated_at">Recently updated</option>
            <option value="created_at">Created date</option>
            <option value="name">Name</option>
          </select>
        </label>
        <button class="secondary-button" type="submit">Apply</button>
      </form>

      @if (loading()) {
        <app-loading-state label="Loading projects…" />
      } @else if (errorMessage()) {
        <div class="state-card" role="alert">{{ errorMessage() }}</div>
      } @else if (projects().length === 0) {
        <app-empty-state
          heading="No projects found"
          message="Create a project or adjust the current filters."
        >
          <a class="primary-button" routerLink="/projects/new">Create project</a>
        </app-empty-state>
      } @else {
        <div class="project-grid">
          @for (project of projects(); track project.id) {
            <article class="project-card">
              <div class="project-card-heading">
                <div>
                  <span class="status-pill" [attr.data-state]="project.status">{{
                    project.status
                  }}</span>
                  <h2>
                    <a [routerLink]="['/projects', project.id]">{{ project.name }}</a>
                  </h2>
                </div>
                <span class="project-language">{{ project.default_language }}</span>
              </div>
              <p>{{ project.description || 'No description provided.' }}</p>
              <div class="project-actions">
                <a class="secondary-button" [routerLink]="['/projects', project.id, 'edit']"
                  >Edit</a
                >
                @if (project.status === 'archived') {
                  <button class="secondary-button" type="button" (click)="restore(project)">
                    Restore
                  </button>
                } @else {
                  <button class="secondary-button" type="button" (click)="archive(project)">
                    Archive
                  </button>
                }
              </div>
            </article>
          }
        </div>
        <nav class="pagination-controls" aria-label="Project pages">
          <button
            class="secondary-button"
            type="button"
            [disabled]="offset() === 0"
            (click)="previousPage()"
          >
            Previous
          </button>
          <span>{{ pageSummary() }}</span>
          <button
            class="secondary-button"
            type="button"
            [disabled]="!hasMore()"
            (click)="nextPage()"
          >
            Next
          </button>
        </nav>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectListPageComponent {
  private readonly api = inject(ProjectApiService);
  private readonly notifications = inject(NotificationService);
  private readonly formBuilder = inject(FormBuilder);
  private readonly limit = 12;
  readonly projects = signal<readonly ProjectResponse[]>([]);
  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly offset = signal(0);
  readonly total = signal(0);
  readonly hasMore = signal(false);
  readonly filters = this.formBuilder.nonNullable.group({
    search: '',
    status: '',
    sortBy: 'updated_at',
  });

  constructor() {
    void this.load();
  }

  pageSummary(): string {
    if (this.total() === 0) return 'No projects';
    const first = this.offset() + 1;
    return `${String(first)}–${String(Math.min(this.offset() + this.limit, this.total()))} of ${String(this.total())}`;
  }

  applyFilters(): void {
    this.offset.set(0);
    void this.load();
  }

  previousPage(): void {
    this.offset.update((value) => Math.max(0, value - this.limit));
    void this.load();
  }

  nextPage(): void {
    if (!this.hasMore()) return;
    this.offset.update((value) => value + this.limit);
    void this.load();
  }

  async archive(project: ProjectResponse): Promise<void> {
    await this.lifecycle(() => this.api.archive(project), 'Project archived.');
  }

  async restore(project: ProjectResponse): Promise<void> {
    await this.lifecycle(() => this.api.restore(project), 'Project restored.');
  }

  private async lifecycle(action: () => Promise<ProjectResponse>, message: string): Promise<void> {
    try {
      await action();
      this.notifications.success(message);
      await this.load();
    } catch (error: unknown) {
      this.notifications.error(error instanceof Error ? error.message : 'Project update failed.');
    }
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.errorMessage.set(null);
    const value = this.filters.getRawValue();
    const query: NonNullable<ListProjectsData['query']> = {
      offset: this.offset(),
      limit: this.limit,
      sort_by: value.sortBy as 'created_at' | 'name' | 'updated_at',
      sort_order: value.sortBy === 'name' ? 'asc' : 'desc',
    };
    if (value.search.trim()) query.search = value.search.trim();
    if (value.status) query.status = value.status as 'active' | 'archived' | 'draft';
    try {
      const page = await this.api.list(query);
      this.projects.set(page.items);
      this.total.set(page.pagination.total);
      this.hasMore.set(page.pagination.has_more);
    } catch (error: unknown) {
      this.errorMessage.set(
        error instanceof Error ? error.message : 'Projects could not be loaded.',
      );
    } finally {
      this.loading.set(false);
    }
  }
}
