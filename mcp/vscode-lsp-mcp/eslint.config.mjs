import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const typescriptConfigs = tseslint.configs.recommended.map((config) => ({
  ...config,
  files: ['packages/*/src/**/*.ts'],
  languageOptions: {
    ...config.languageOptions,
    globals: globals.node,
  },
}));

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/**',
      '.vscode-test/**',
      'packages/*/dist/**',
      'packages/*/build/**',
      'dist/**',
      'coverage/**',
    ],
  },
  {
    ...js.configs.recommended,
    files: [
      'eslint.config.mjs',
      'scripts/**/*.mjs',
      'packages/*/scripts/**/*.mjs',
      'tests/**/*.mjs',
    ],
    languageOptions: {
      globals: globals.node,
    },
  },
  ...typescriptConfigs,
);
