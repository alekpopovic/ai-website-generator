import { HttpErrorResponse } from '@angular/common/http';

import type { ProblemDetail } from './generated/types.gen';

export function mapProblemDetails(error: unknown): ProblemDetail | null {
  const candidate: unknown = error instanceof HttpErrorResponse ? error.error : error;
  return isProblemDetails(candidate) ? candidate : null;
}

export function isProblemDetails(value: unknown): value is ProblemDetail {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record['title'] === 'string' &&
    typeof record['status'] === 'number' &&
    typeof record['code'] === 'string' &&
    typeof record['request_id'] === 'string'
  );
}
