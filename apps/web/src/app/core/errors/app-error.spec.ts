import { HttpErrorResponse } from '@angular/common/http';

import { toAppError } from './app-error';

describe('toAppError', () => {
  it('maps an unavailable HTTP connection to a typed network error', () => {
    const result = toAppError(new HttpErrorResponse({ status: 0 }));

    expect(result.code).toBe('network');
    expect(result.status).toBe(0);
  });

  it('does not expose an arbitrary exception message to the user', () => {
    const result = toAppError(new Error('private implementation detail'));

    expect(result.code).toBe('unknown');
    expect(result.message).not.toContain('private implementation detail');
  });

  it('maps generated problem details without duplicating the API contract', () => {
    const result = toAppError(
      new HttpErrorResponse({
        status: 503,
        error: {
          title: 'Service Unavailable',
          status: 503,
          detail: 'A required data service is unavailable.',
          code: 'database_unavailable',
          request_id: 'request-1',
        },
      }),
    );

    expect(result.code).toBe('server');
    expect(result.problem?.request_id).toBe('request-1');
  });
});
