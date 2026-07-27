import { HttpErrorResponse } from '@angular/common/http';

import { mapProblemDetails } from './problem-details';

describe('mapProblemDetails', () => {
  it('maps an RFC 7807 response using the generated contract', () => {
    const problem = {
      type: 'about:blank',
      title: 'Unavailable',
      status: 503,
      code: 'dependency_unavailable',
      request_id: 'request-1',
    };

    expect(mapProblemDetails(new HttpErrorResponse({ error: problem, status: 503 }))).toEqual(
      problem,
    );
  });

  it('rejects unrelated JSON', () => {
    expect(mapProblemDetails({ message: 'not a problem document' })).toBeNull();
  });
});
