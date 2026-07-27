import { HttpErrorResponse } from '@angular/common/http';
import { mapProblemDetails } from '@platform/api-client';
import type { ProblemDetail } from '@platform/api-client';

export type AppErrorCode =
  'bad-request' | 'forbidden' | 'network' | 'not-found' | 'server' | 'unauthorized' | 'unknown';

export class AppError extends Error {
  constructor(
    readonly code: AppErrorCode,
    message: string,
    readonly status: number | null,
    readonly problem?: ProblemDetail,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = 'AppError';
  }
}

export function toAppError(error: unknown): AppError {
  if (error instanceof AppError) {
    return error;
  }
  if (error instanceof HttpErrorResponse) {
    return mapHttpError(error);
  }
  const problem = mapProblemDetails(error);
  if (problem !== null) {
    return new AppError(
      mapProblemCode(problem.status),
      problem.detail ?? problem.title,
      problem.status,
      problem,
      { cause: error },
    );
  }
  return new AppError('unknown', 'Something went wrong. Please try again.', null, undefined, {
    cause: error,
  });
}

function mapHttpError(error: HttpErrorResponse): AppError {
  if (error.status === 0) {
    return new AppError('network', 'The service could not be reached.', 0, undefined, {
      cause: error,
    });
  }

  const problem = mapProblemDetails(error);
  if (problem !== null) {
    return new AppError(
      mapProblemCode(problem.status),
      problem.detail ?? problem.title,
      problem.status,
      problem,
      { cause: error },
    );
  }

  const byStatus: Partial<Record<number, readonly [AppErrorCode, string]>> = {
    400: ['bad-request', 'The request could not be processed.'],
    401: ['unauthorized', 'Your session is not authorized.'],
    403: ['forbidden', 'You do not have permission to perform this action.'],
    404: ['not-found', 'The requested resource was not found.'],
  };
  const mapped = byStatus[error.status] ?? ['server', 'The service encountered an error.'];
  return new AppError(mapped[0], mapped[1], error.status, undefined, { cause: error });
}

function mapProblemCode(status: number): AppErrorCode {
  if (status === 400 || status === 422) return 'bad-request';
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not-found';
  return 'server';
}
