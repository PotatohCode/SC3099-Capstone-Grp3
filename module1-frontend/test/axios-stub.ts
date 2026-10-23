/** Test helpers that stub the axios adapter so requests run through the real interceptors without a network. */
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import httpClient from '@/lib/utils/http-client'

export interface RecordedRequest {
  method: string | undefined
  url: string | undefined
  data: unknown
  authorization: string | undefined
  timeout: number | undefined
}

export type StubReply =
  | { status: number; data?: unknown; headers?: Record<string, string> }
  | { network: true }

/** Builds an AxiosError carrying an HTTP response. */
export function httpError(status: number, data: unknown = {}, headers: Record<string, string> = {}): AxiosError {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  return new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, {}, {
    status,
    statusText: String(status),
    data,
    headers,
    config,
  })
}

/** Builds an AxiosError without a response, like a network failure. */
export function networkError(): AxiosError {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  return new AxiosError('Network Error', 'ERR_NETWORK', config, {})
}

/** Installs an adapter on httpClient that answers from the given handler and records each request. */
export function stubAdapter(handler: (req: RecordedRequest) => StubReply): RecordedRequest[] {
  const calls: RecordedRequest[] = []
  httpClient.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const auth = config.headers?.Authorization
    const req: RecordedRequest = {
      method: config.method,
      url: config.url,
      data: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
      authorization: typeof auth === 'string' ? auth : undefined,
      timeout: config.timeout,
    }
    calls.push(req)
    const reply = handler(req)
    if ('network' in reply) throw new AxiosError('Network Error', 'ERR_NETWORK', config, {})
    const response = {
      status: reply.status,
      statusText: String(reply.status),
      data: reply.data ?? {},
      headers: reply.headers ?? {},
      config,
    }
    if (reply.status >= 400) {
      throw new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, {}, response)
    }
    return response
  }
  return calls
}
