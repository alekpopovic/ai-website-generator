import { Injectable, inject } from '@angular/core';
import {
  AnalysisProfiles,
  type ListSectionPatternsData,
  type PageProfileResponse,
  type PageResponsePageProfileResponse,
  type PageResponseSectionPatternResponse,
  type SectionPatternDetailResponse,
  type SectionPatternFacetsResponse,
  type SectionPatternResponse,
} from '@platform/api-client';

import { toAppError } from '../errors/app-error';

export type ApprovalState = 'approved' | 'needs_review' | 'rejected';
export type PatternFilterQuery = Omit<
  NonNullable<ListSectionPatternsData['query']>,
  'limit' | 'offset'
>;

@Injectable({ providedIn: 'root' })
export class AnalysisReviewApiService {
  private readonly profiles = inject(AnalysisProfiles);

  async pageProfiles(projectId: string): Promise<PageResponsePageProfileResponse> {
    return this.unwrap(
      this.profiles.listPageProfiles({
        path: { project_id: projectId },
        query: { current_only: true, limit: 100, offset: 0 },
      }),
    );
  }

  async sectionPatterns(
    projectId: string,
    filters: PatternFilterQuery = {},
    offset = 0,
  ): Promise<PageResponseSectionPatternResponse> {
    const query: NonNullable<ListSectionPatternsData['query']> = {
      limit: 100,
      offset,
      ...filters,
    };
    return this.unwrap(
      this.profiles.listSectionPatterns({
        path: { project_id: projectId },
        query,
      }),
    );
  }

  async patternFacets(
    projectId: string,
    filters: PatternFilterQuery = {},
  ): Promise<SectionPatternFacetsResponse> {
    return this.unwrap(
      this.profiles.getSectionPatternFacets({
        path: { project_id: projectId },
        query: filters,
      }),
    );
  }

  async patternDetail(projectId: string, patternId: string): Promise<SectionPatternDetailResponse> {
    return this.unwrap(
      this.profiles.getSectionPatternDetail({
        path: { project_id: projectId, pattern_id: patternId },
      }),
    );
  }

  async curatePatterns(
    projectId: string,
    patterns: readonly SectionPatternResponse[],
    approvalState: ApprovalState,
    note: string | null,
  ): Promise<readonly SectionPatternResponse[]> {
    return this.unwrap(
      this.profiles.bulkCurateSectionPatterns({
        path: { project_id: projectId },
        body: {
          items: patterns.map(({ id, version }) => ({ id, version })),
          approval_state: approvalState,
          note,
        },
      }),
    );
  }

  async curatePage(
    projectId: string,
    profile: PageProfileResponse,
    approvalState: ApprovalState,
    note: string | null,
  ): Promise<PageProfileResponse> {
    return this.unwrap(
      this.profiles.curatePageProfile({
        path: { project_id: projectId, profile_id: profile.id },
        body: { approval_state: approvalState, note, version: profile.version },
      }),
    );
  }

  async curatePattern(
    projectId: string,
    pattern: SectionPatternResponse,
    approvalState: ApprovalState,
    note: string | null,
  ): Promise<SectionPatternResponse> {
    return this.unwrap(
      this.profiles.curateSectionPattern({
        path: { project_id: projectId, pattern_id: pattern.id },
        body: { approval_state: approvalState, note, version: pattern.version },
      }),
    );
  }

  private async unwrap<T>(
    request: Promise<{ data?: T; error?: unknown }>,
  ): Promise<NonNullable<T>> {
    const result = await request;
    if (result.error !== undefined) throw toAppError(result.error);
    if (result.data === undefined) throw new Error('The API returned no response body.');
    return result.data as NonNullable<T>;
  }
}
