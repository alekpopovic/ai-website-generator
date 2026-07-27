import { isProblemDetails, type ProblemDetail } from '@platform/api-client';

export class AuthenticationError extends Error {
  constructor(readonly problem: ProblemDetail | null) {
    super(problem?.detail ?? problem?.title ?? 'Authentication request failed.');
    this.name = 'AuthenticationError';
  }

  fieldError(name: string): string | null {
    return this.problem?.invalid_parameters?.find((item) => item.name === name)?.reason ?? null;
  }
}

export function toAuthenticationError(value: unknown): AuthenticationError {
  if (isProblemDetails(value)) return new AuthenticationError(value);
  if (typeof value === 'object' && value !== null && 'problem' in value) {
    const problem = (value as { readonly problem?: unknown }).problem;
    if (isProblemDetails(problem)) return new AuthenticationError(problem);
  }
  return new AuthenticationError(null);
}
