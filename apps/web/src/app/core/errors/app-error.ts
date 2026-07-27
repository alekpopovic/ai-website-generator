import { HttpErrorResponse } from '@angular/common/http';
import { mapProblemDetails } from '@platform/api-client';
import type { ProblemDetail } from '@platform/api-client';

export type AppErrorCode =
  'bad-request' | 'forbidden' | 'network' | 'not-found' | 'server' | 'unauthorized' | 'unknown';

export interface AppError {
  readonly code: AppErrorCode;
  readonly message: string;
  readonly status: number | null;
  readonly problem?: ProblemDetail;
  readonly cause?: unknown;
}

export function toAppError(error: unknown): AppError {
  if (isAppError(error)) {
    return error;
  }
  if (error instanceof HttpErrorResponse) {
    return mapHttpError(error);
  }
  return {
    code: 'unknown',
    message: 'Something went wrong. Please try again.',
    status: null,
    cause: error,
  };
}

function mapHttpError(error: HttpErrorResponse): AppError {
  if (error.status === 0) {
    return {
      code: 'network',
      message: 'The service could not be reached.',
      status: 0,
      cause: error,
    };
  }

  const problem = mapProblemDetails(error);
  if (problem !== null) {
    return {
      code: mapProblemCode(problem.status),
      message: problem.detail ?? problem.title,
      status: problem.status,
      problem,
      cause: error,
    };
  }

  const byStatus: Partial<Record<number, readonly [AppErrorCode, string]>> = {
    400: ['bad-request', 'The request could not be processed.'],
    401: ['unauthorized', 'Your session is not authorized.'],
    403: ['forbidden', 'You do not have permission to perform this action.'],
    404: ['not-found', 'The requested resource was not found.'],
  };
  const mapped = byStatus[error.status] ?? ['server', 'The service encountered an error.'];
  return { code: mapped[0], message: mapped[1], status: error.status, cause: error };
}

function mapProblemCode(status: number): AppErrorCode {
  if (status === 400 || status === 422) return 'bad-request';
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not-found';
  return 'server';
}

function isAppError(error: unknown): error is AppError {
  if (typeof error !== 'object' || error === null) {
    return false;
  }
  const candidate = error as Partial<AppError>;
  return typeof candidate.code === 'string' && typeof candidate.message === 'string';
}
