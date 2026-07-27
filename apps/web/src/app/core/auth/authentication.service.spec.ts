import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ApiAccessTokenStore, Auth, type UserResponse } from '@platform/api-client';

import { AuthenticationService } from './authentication.service';

const USER = {
  id: '9af6cdda-7e40-4a53-86c9-f3bea98d0ed4',
  email: 'person@example.test',
  display_name: 'Person',
  email_verified: true,
  created_at: '2026-07-27T10:00:00Z',
} satisfies UserResponse;

describe('AuthenticationService', () => {
  it('keeps the access token only in its in-memory store', async () => {
    const persisted = new Map<string, string>([['unrelated', 'preserved']]);
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => persisted.get(key) ?? null,
      setItem: (key: string, value: string) => persisted.set(key, value),
    });
    const api = {
      login: vi.fn(() =>
        Promise.resolve({
          data: { access_token: 'memory-token', expires_in: 300, user: USER },
        }),
      ),
    };
    const router = { navigateByUrl: vi.fn(() => Promise.resolve(true)) };
    TestBed.configureTestingModule({
      providers: [
        AuthenticationService,
        ApiAccessTokenStore,
        { provide: Auth, useValue: api },
        { provide: Router, useValue: router },
      ],
    });
    const service = TestBed.inject(AuthenticationService);
    const tokens = TestBed.inject(ApiAccessTokenStore);

    await service.login({ email: USER.email, password: 'not-persisted' }); // pragma: allowlist secret

    expect(tokens.accessToken()).toBe('memory-token');
    expect(service.currentUser()).toEqual(USER);
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('unrelated')).toBe('preserved');
  });
});
