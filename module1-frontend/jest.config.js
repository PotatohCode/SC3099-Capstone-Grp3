/** Jest config: Next's SWC transform, jsdom, and axios mapped to its CJS build because jsdom otherwise resolves axios's ESM browser build, which Jest cannot parse. */
const nextJest = require('next/jest')

module.exports = nextJest({ dir: './' })({
  testEnvironment: 'jsdom',
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
    '^axios$': '<rootDir>/node_modules/axios/dist/node/axios.cjs',
  },
  setupFilesAfterEnv: ['<rootDir>/test/setup.ts'],
  testMatch: ['**/__tests__/**/*.test.ts?(x)'],
  collectCoverageFrom: ['lib/**/*.{ts,tsx}', 'components/**/*.tsx', 'app/**/*.tsx', '!**/__tests__/**'],
  coverageReporters: ['text', 'text-summary'],
})
