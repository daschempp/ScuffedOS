import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Unmount React trees + reset jsdom between tests so state can't leak.
afterEach(() => {
  cleanup()
})
