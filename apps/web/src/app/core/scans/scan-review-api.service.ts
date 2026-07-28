import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import {
  PlatformApiConfiguration,
  ScanCampaigns,
  type CrawlPageDetailResponse,
  type CrawlPageResponse,
  type ListScanCampaignFailuresData,
  type ListScanCampaignPagesData,
  type ListScanCampaignTargetsData,
  type ListScanCampaignsData,
  type PageResponseCampaignActivityResponse,
  type PageResponseCrawlPageWithScansResponse,
  type PageResponseScanCampaignResponse,
  type PageResponseScanFailureResponse,
  type PageResponseScanTargetResponse,
  type ScanCampaignCreateRequest,
  type ScanCampaignResponse,
  type ScanCampaignSummaryResponse,
} from '@platform/api-client';

import { toAppError } from '../errors/app-error';
import { firstValueFrom } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class ScanReviewApiService {
  private readonly scans = inject(ScanCampaigns);
  private readonly configuration = inject(PlatformApiConfiguration);
  private readonly http = inject(HttpClient);

  async campaigns(
    projectId: string,
    query: NonNullable<ListScanCampaignsData['query']>,
  ): Promise<PageResponseScanCampaignResponse> {
    return this.unwrap(this.scans.listScanCampaigns({ path: { project_id: projectId }, query }));
  }

  async create(projectId: string, body: ScanCampaignCreateRequest): Promise<ScanCampaignResponse> {
    return this.unwrap(this.scans.createScanCampaign({ path: { project_id: projectId }, body }));
  }

  async campaign(projectId: string, campaignId: string): Promise<ScanCampaignResponse> {
    return this.unwrap(
      this.scans.getScanCampaign({ path: { project_id: projectId, campaign_id: campaignId } }),
    );
  }

  async summary(projectId: string, campaignId: string): Promise<ScanCampaignSummaryResponse> {
    return this.unwrap(
      this.scans.getScanCampaignSummary({
        path: { project_id: projectId, campaign_id: campaignId },
      }),
    );
  }

  async pages(
    projectId: string,
    campaignId: string,
    query: NonNullable<ListScanCampaignPagesData['query']>,
  ): Promise<PageResponseCrawlPageWithScansResponse> {
    return this.unwrap(
      this.scans.listScanCampaignPages({
        path: { project_id: projectId, campaign_id: campaignId },
        query,
      }),
    );
  }

  async targets(
    projectId: string,
    campaignId: string,
    offset = 0,
    status?: 'accepted' | 'completed' | 'failed' | 'pending' | 'rejected',
  ): Promise<PageResponseScanTargetResponse> {
    const query: NonNullable<ListScanCampaignTargetsData['query']> = {
      offset,
      limit: 20,
    };
    if (status !== undefined) query.status = status;
    return this.unwrap(
      this.scans.listScanCampaignTargets({
        path: { project_id: projectId, campaign_id: campaignId },
        query,
      }),
    );
  }

  async page(
    projectId: string,
    campaignId: string,
    pageId: string,
  ): Promise<CrawlPageDetailResponse> {
    return this.unwrap(
      this.scans.getScanCampaignPage({
        path: { project_id: projectId, campaign_id: campaignId, page_id: pageId },
      }),
    );
  }

  async failures(
    projectId: string,
    campaignId: string,
    query: NonNullable<ListScanCampaignFailuresData['query']>,
  ): Promise<PageResponseScanFailureResponse> {
    return this.unwrap(
      this.scans.listScanCampaignFailures({
        path: { project_id: projectId, campaign_id: campaignId },
        query,
      }),
    );
  }

  async activity(
    projectId: string,
    campaignId: string,
    offset = 0,
  ): Promise<PageResponseCampaignActivityResponse> {
    return this.unwrap(
      this.scans.listScanCampaignActivity({
        path: { project_id: projectId, campaign_id: campaignId },
        query: { offset, limit: 20 },
      }),
    );
  }

  async retrySelected(
    projectId: string,
    campaign: ScanCampaignResponse,
    failureIds: readonly string[],
  ): Promise<ScanCampaignResponse> {
    return this.unwrap(
      this.scans.retrySelectedScanCampaignFailures({
        path: { project_id: projectId, campaign_id: campaign.id },
        body: {
          version: campaign.version,
          idempotency_key: crypto.randomUUID(),
          failure_ids: [...failureIds],
        },
      }),
    );
  }

  async overrideRepresentative(
    projectId: string,
    campaignId: string,
    page: CrawlPageResponse,
    selection: 'automatic' | 'exclude' | 'include',
    reason: string,
  ): Promise<CrawlPageResponse> {
    return this.unwrap(
      this.scans.overrideScanCampaignPageRepresentative({
        path: { project_id: projectId, campaign_id: campaignId, page_id: page.id },
        body: { version: page.version, selection, reason: reason || null },
      }),
    );
  }

  screenshotUrl(projectId: string, campaignId: string, artifactId: string): string {
    return this.configuration.buildUrl(
      `/api/v1/projects/${encodeURIComponent(projectId)}/scan-campaigns/${encodeURIComponent(campaignId)}/artifacts/${encodeURIComponent(artifactId)}/screenshot`,
    );
  }

  screenshot(projectId: string, campaignId: string, artifactId: string): Promise<Blob> {
    return firstValueFrom(
      this.http.get(this.screenshotUrl(projectId, campaignId, artifactId), {
        responseType: 'blob',
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
