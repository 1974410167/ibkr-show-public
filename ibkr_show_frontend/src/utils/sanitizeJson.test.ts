import { describe, expect, it } from 'vitest'

import { isSensitiveJsonKey, sanitizeJsonValue } from './sanitizeJson'

describe('sanitizeJsonValue', () => {
  it('redacts sensitive credential fields', () => {
    const result = sanitizeJsonValue({
      api_key: 'abc',
      token: 'abc',
      access_token: 'abc',
      refresh_token: 'abc',
      authorization: 'Bearer abc',
      cookie: 'sid=abc',
      password: 'abc',
      secret: 'abc',
      private_key: 'abc',
      session_id: 'abc',
      openai_api_key: 'abc',
      client_secret: 'abc',
    })

    expect(result).toEqual({
      api_key: '***',
      token: '***',
      access_token: '***',
      refresh_token: '***',
      authorization: '***',
      cookie: '***',
      password: '***',
      secret: '***',
      private_key: '***',
      session_id: '***',
      openai_api_key: '***',
      client_secret: '***',
    })
  })

  it('keeps token metric fields visible', () => {
    const metrics = {
      prompt_tokens: 100,
      completion_tokens: 20,
      total_tokens: 120,
      cached_tokens: 30,
      reasoning_tokens: 10,
      token_count: 3,
      max_tokens: 4096,
      input_tokens: 100,
      output_tokens: 20,
      tokens: 120,
      total_token_count: 120,
      prompt_token_count: 100,
      completion_token_count: 20,
    }

    expect(sanitizeJsonValue(metrics)).toEqual(metrics)
    Object.keys(metrics).forEach((key) => {
      expect(isSensitiveJsonKey(key)).toBe(false)
    })
  })

  it('redacts reasoning and thinking fields', () => {
    const result = sanitizeJsonValue({
      reasoning: 'internal chain',
      thinking: 'step by step',
      chain_of_thought: 'because...',
      output: 'visible',
    })

    expect(result).toEqual({
      reasoning: '***',
      thinking: '***',
      chain_of_thought: '***',
      output: 'visible',
    })
  })

  it('recursively sanitizes nested objects and arrays without hiding usage tokens', () => {
    const result = sanitizeJsonValue({
      usage: { total_tokens: 120, access_token: 'abc' },
      calls: [{ prompt_tokens: 100, authorization: 'Bearer abc' }],
    })

    expect(result).toEqual({
      usage: { total_tokens: 120, access_token: '***' },
      calls: [{ prompt_tokens: 100, authorization: '***' }],
    })
  })
})
