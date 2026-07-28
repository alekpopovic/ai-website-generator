import { Injectable, inject } from '@angular/core';
import {
  AnalysisProfiles,
  type PageProfileResponse,
  type PageResponsePageProfileResponse,
  type PageResponseSectionPatternResponse,
  type SectionPatternResponse,
} from '@platform/api-client';

import { toAppError } from '../errors/app-error';

export type ApprovalState = 'approved' | 'needs_review' | 'rejected';

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
    approvalState?: ApprovalState,
  ): Promise<PageResponseSectionPatternResponse> {
    const query: { limit: number; offset: number; approval_state?: ApprovalState } = {
      limit: 100,
      offset: 0,
    };
    if (approvalState !== undefined) query.approval_state = approvalState;
    return this.unwrap(
      this.profiles.listSectionPatterns({
        path: { project_id: projectId },
        query,
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
