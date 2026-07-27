import type { ProblemDetail } from '@platform/api-client';

import { toAuthenticationError } from './authentication-error';

describe('authentication error mapping', () => {
  it('retains typed field validation from an application HTTP error', () => {
    const problem = {
      title: 'Unprocessable Entity',
      status: 422,
      code: 'request_validation_failed',
      request_id: 'request-test',
      invalid_parameters: [{ name: 'password', location: 'body', reason: 'Password is weak.' }],
    } satisfies ProblemDetail;

    const error = toAuthenticationError({ code: 'bad-request', message: 'Invalid', problem });

    expect(error.fieldError('password')).toBe('Password is weak.');
    expect(error.problem).toEqual(problem);
  });
});
