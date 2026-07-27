import { TestBed } from '@angular/core/testing';

import { RuntimeConfigService } from './runtime-config';

describe('RuntimeConfigService', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads and normalizes public runtime configuration', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            apiBaseUrl: 'http://localhost:8000/',
            previewBaseUrl: 'https://preview.example.test/',
            supportUrl: null,
          }),
          { status: 200 },
        ),
      ),
    );
    const service = TestBed.inject(RuntimeConfigService);

    await service.load();

    expect(service.config).toEqual({
      apiBaseUrl: 'http://localhost:8000',
      previewBaseUrl: 'https://preview.example.test',
      supportUrl: null,
    });
  });

  it('rejects non-HTTP endpoints', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            apiBaseUrl: 'file:///etc/passwd',
            previewBaseUrl: 'https://preview.example.test',
            supportUrl: null,
          }),
          { status: 200 },
        ),
      ),
    );
    const service = TestBed.inject(RuntimeConfigService);

    await expect(service.load()).rejects.toThrow('apiBaseUrl must use HTTP or HTTPS');
    expect(service.state().status).toBe('error');
  });
});
