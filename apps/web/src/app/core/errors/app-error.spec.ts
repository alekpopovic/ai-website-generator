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
});
