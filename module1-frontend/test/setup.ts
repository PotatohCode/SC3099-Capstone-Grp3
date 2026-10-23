/** Resets browser storage between tests. */
beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})

afterEach(() => {
  const { default: httpClient } = jest.requireActual('@/lib/utils/http-client') as typeof import('@/lib/utils/http-client')
  httpClient.defaults.adapter = async () => {
    throw new Error('Unexpected HTTP request: stub the adapter with stubAdapter() in this test')
  }
})
