import { Injectable, inject } from '@angular/core';
import {
  Datasets,
  type DatasetResponse,
  type DatasetVersionDetailResponse,
  type DatasetVersionResponse,
  type PageResponseDatasetItemResponse,
  type PageResponseDatasetResponse,
  type PageResponseDatasetVersionResponse,
} from '@platform/api-client';

import { toAppError } from '../errors/app-error';

@Injectable({ providedIn: 'root' })
export class DatasetApiService {
  private readonly api = inject(Datasets);

  async list(projectId: string, offset = 0): Promise<PageResponseDatasetResponse> {
    return this.unwrap(
      this.api.listDatasets({
        path: { project_id: projectId },
        query: { offset, limit: 100 },
      }),
    );
  }

  async get(projectId: string, datasetId: string): Promise<DatasetResponse> {
    return this.unwrap(
      this.api.getDataset({ path: { project_id: projectId, dataset_id: datasetId } }),
    );
  }

  async versions(
    projectId: string,
    datasetId: string,
  ): Promise<PageResponseDatasetVersionResponse> {
    return this.unwrap(
      this.api.listDatasetVersions({
        path: { project_id: projectId, dataset_id: datasetId },
        query: { offset: 0, limit: 100 },
      }),
    );
  }

  async createVersion(projectId: string, datasetId: string): Promise<DatasetVersionResponse> {
    return this.unwrap(
      this.api.createDatasetVersion({
        path: { project_id: projectId, dataset_id: datasetId },
        body: {},
      }),
    );
  }

  async version(
    projectId: string,
    datasetId: string,
    versionId: string,
  ): Promise<DatasetVersionDetailResponse> {
    return this.unwrap(
      this.api.getDatasetVersion({
        path: { project_id: projectId, dataset_id: datasetId, version_id: versionId },
      }),
    );
  }

  async seal(
    projectId: string,
    datasetId: string,
    version: DatasetVersionResponse,
  ): Promise<DatasetVersionDetailResponse> {
    return this.unwrap(
      this.api.sealDatasetVersion({
        path: {
          project_id: projectId,
          dataset_id: datasetId,
          version_id: version.id,
        },
        body: { version: version.version },
      }),
    );
  }

  async items(
    projectId: string,
    datasetId: string,
    versionId: string,
  ): Promise<PageResponseDatasetItemResponse> {
    return this.unwrap(
      this.api.listDatasetItems({
        path: { project_id: projectId, dataset_id: datasetId, version_id: versionId },
        query: { offset: 0, limit: 100 },
      }),
    );
  }

  private async unwrap<T>(
    request: Promise<{ data?: T | undefined; error?: unknown }>,
  ): Promise<NonNullable<T>> {
    const result = await request;
    if (result.error !== undefined) throw toAppError(result.error);
    if (result.data === undefined) throw new Error('The API returned no response body.');
    return result.data as NonNullable<T>;
  }
}
