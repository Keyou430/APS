import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    exclude: ['tests/**', 'node_modules/**', 'dist/**'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    globals: true,
    environment: 'jsdom',
  },
})
