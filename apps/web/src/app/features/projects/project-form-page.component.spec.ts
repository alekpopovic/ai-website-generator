import { parseProjectSettings } from './project-form-page.component';

describe('project settings parsing', () => {
  it('accepts objects and rejects arrays', () => {
    expect(parseProjectSettings('{"palette":"calm"}')).toEqual({ palette: 'calm' });
    expect(() => parseProjectSettings('["not-an-object"]')).toThrow('JSON object');
  });
});
