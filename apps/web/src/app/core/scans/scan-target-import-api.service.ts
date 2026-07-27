import { HttpClient } from '@angular/common/http';
import type { HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import {
  PlatformApiConfiguration,
  ScanCampaigns,
  type ImportScanCampaignTargetsData,
  type ScanTargetImportResponse,
} from '@platform/api-client';
import type { Observable } from 'rxjs';

import { toAppError } from '../errors/app-error';

export type TargetImportSource = ImportScanCampaignTargetsData['query']['source_type'];

export interface TargetImportUpload {
  readonly projectId: string;
  readonly campaignId: string;
  readonly body: Blob;
  readonly sourceType: TargetImportSource;
  readonly filename?: string | undefined;
  readonly dryRun: boolean;
  readonly authorizationAttested: boolean;
}

@Injectable({ providedIn: 'root' })
export class ScanTargetImportApiService {
  private readonly http = inject(HttpClient);
  private readonly configuration = inject(PlatformApiConfiguration);
  private readonly scans = inject(ScanCampaigns);

  upload(request: TargetImportUpload): Observable<HttpEvent<ScanTargetImportResponse>> {
    const url = this.configuration.buildUrl(
      `/api/v1/projects/${encodeURIComponent(request.projectId)}/scan-campaigns/${encodeURIComponent(request.campaignId)}/target-imports`,
      {
        source_type: request.sourceType,
        authorization_attested: request.authorizationAttested,
        dry_run: request.dryRun,
        filename: request.filename,
      },
    );
    return this.http.post<ScanTargetImportResponse>(url, request.body, {
      headers: { 'Content-Type': request.sourceType === 'csv' ? 'text/csv' : 'text/plain' },
      observe: 'events',
      reportUploadProgress: true,
    });
  }

  async commit(
    projectId: string,
    campaignId: string,
    targetImport: ScanTargetImportResponse,
  ): Promise<ScanTargetImportResponse> {
    const result = await this.scans.commitScanTargetImport({
      path: { project_id: projectId, campaign_id: campaignId, import_id: targetImport.id },
      body: { version: targetImport.version, authorization_attested: true },
    });
    if (result.error !== undefined) throw toAppError(result.error);
    return result.data;
  }

  downloadErrors(projectId: string, campaignId: string, importId: string): Observable<Blob> {
    const url = this.configuration.buildUrl(
      `/api/v1/projects/${encodeURIComponent(projectId)}/scan-campaigns/${encodeURIComponent(campaignId)}/target-imports/${encodeURIComponent(importId)}/errors.csv`,
    );
    return this.http.get(url, { responseType: 'blob' });
  }
}
