import { Injectable, inject } from '@angular/core';
import {
  Projects,
  type ListProjectsData,
  type PageResponseProjectResponse,
  type ProjectCreateRequest,
  type ProjectResponse,
  type ProjectUpdateRequest,
} from '@platform/api-client';

import { toAppError } from '../errors/app-error';

@Injectable({ providedIn: 'root' })
export class ProjectApiService {
  private readonly api = inject(Projects);

  async list(query: NonNullable<ListProjectsData['query']>): Promise<PageResponseProjectResponse> {
    const result = await this.api.listProjects({ query });
    if (result.error !== undefined) throw toAppError(result.error);
    return result.data;
  }

  async create(payload: ProjectCreateRequest): Promise<ProjectResponse> {
    const result = await this.api.createProject({ body: payload });
    if (result.error !== undefined) throw toAppError(result.error);
    return result.data;
  }

  async get(projectId: string): Promise<ProjectResponse> {
    const result = await this.api.getProject({ path: { project_id: projectId } });
    if (result.error !== undefined) throw toAppError(result.error);
    return result.data;
  }

  async update(projectId: string, payload: ProjectUpdateRequest): Promise<ProjectResponse> {
    const result = await this.api.updateProject({
      path: { project_id: projectId },
      body: payload,
    });
    if (result.error !== undefined) throw toAppError(result.error);
    return result.data;
  }

  async archive(project: ProjectResponse): Promise<ProjectResponse> {
    const result = await this.api.archiveProject({
      path: { project_id: project.id },
      body: { version: project.version },
    });
    if (result.error !== undefined) throw toAppError(result.error);
    return result.data;
  }

  async restore(project: ProjectResponse): Promise<ProjectResponse> {
    const result = await this.api.restoreProject({
      path: { project_id: project.id },
      body: { version: project.version },
    });
    if (result.error !== undefined) throw toAppError(result.error);
    return result.data;
  }
}
