import { PlatformApiConfiguration } from './configuration';

describe('PlatformApiConfiguration', () => {
  it('builds encoded SSE URLs against the configured API origin', () => {
    const configuration = new PlatformApiConfiguration();
    configuration.configure({ baseUrl: 'https://api.example.test/' });

    expect(configuration.buildSseUrl('/api/v1/jobs/job-1/events', { cursor: 'a b' })).toBe(
      'https://api.example.test/api/v1/jobs/job-1/events?cursor=a+b',
    );
  });

  it('rejects absolute SSE paths', () => {
    const configuration = new PlatformApiConfiguration();
    configuration.configure({ baseUrl: 'https://api.example.test' });

    expect(() => configuration.buildSseUrl('//untrusted.example/events')).toThrow(
      'SSE paths must be relative',
    );
  });

  it('builds API URLs and omits absent query values', () => {
    const configuration = new PlatformApiConfiguration();
    configuration.configure({ baseUrl: 'https://api.example.test/' });

    expect(
      configuration.buildUrl('/api/v1/imports', {
        dry_run: true,
        filename: 'targets.csv',
        empty: null,
      }),
    ).toBe('https://api.example.test/api/v1/imports?dry_run=true&filename=targets.csv');
  });
});
