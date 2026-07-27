import js from '@eslint/js';
import json from '@eslint/json';
import markdown from '@eslint/markdown';
import angular from 'angular-eslint';
import yml from 'eslint-plugin-yml';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/.angular/**',
      '**/.venv/**',
      '**/artifacts/**',
      '**/coverage/**',
      '**/dist/**',
      '**/generated/**',
      '**/node_modules/**',
      '**/playwright-report/**',
      '**/site-output/**',
      '**/test-results/**',
      'pnpm-lock.yaml',
      'uv.lock',
    ],
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    extends: [js.configs.recommended],
  },
  {
    files: ['**/*.ts'],
    extends: [...tseslint.configs.strictTypeChecked, ...tseslint.configs.stylisticTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ['apps/web/**/*.ts'],
    extends: [...angular.configs.tsRecommended],
    processor: angular.processInlineTemplates,
    rules: {
      // Angular components are framework entry points and may intentionally have no class members.
      '@typescript-eslint/no-extraneous-class': 'off',
      // Angular's built-in validator collection exposes safe static functions.
      '@typescript-eslint/unbound-method': 'off',
    },
  },
  {
    files: ['apps/web/**/*.html'],
    extends: [...angular.configs.templateRecommended, ...angular.configs.templateAccessibility],
  },
  {
    files: ['**/*.json'],
    plugins: { json },
    language: 'json/json',
    rules: json.configs.recommended.rules,
  },
  ...yml.configs.recommended,
  ...yml.configs.prettier,
  ...markdown.configs.recommended,
  {
    files: ['**/*.md'],
    language: 'markdown/gfm',
  },
  {
    linterOptions: {
      reportUnusedDisableDirectives: 'error',
    },
  },
);
