import { Injectable, InjectionToken, inject } from '@angular/core';
import {
  ApiAccessTokenStore,
  ApiRefreshCoordinator,
  PlatformApiConfiguration,
  type JobEventPollResponse,
  type JobEventResponse,
} from '@platform/api-client';
import { Observable, firstValueFrom } from 'rxjs';

export type JobEventFetch = typeof fetch;
export const JOB_EVENT_FETCH = new InjectionToken<JobEventFetch>('JOB_EVENT_FETCH', {
  providedIn: 'root',
  factory: () => globalThis.fetch.bind(globalThis),
});

const TERMINAL_STATES = new Set(['succeeded', 'failed', 'cancelled']);

@Injectable({ providedIn: 'root' })
export class JobEventStreamService {
  private readonly configuration = inject(PlatformApiConfiguration);
  private readonly tokens = inject(ApiAccessTokenStore);
  private readonly refresh = inject(ApiRefreshCoordinator);
  private readonly request = inject(JOB_EVENT_FETCH);
  private readonly active = new Set<AbortController>();

  watch(projectId: string, jobId: string): Observable<JobEventResponse> {
    return new Observable((subscriber) => {
      const controller = new AbortController();
      this.active.add(controller);
      void this.consume(projectId, jobId, controller, subscriber);
      return () => {
        controller.abort();
        this.active.delete(controller);
      };
    });
  }

  closeAll(): void {
    for (const controller of this.active) controller.abort();
    this.active.clear();
  }

  private async consume(
    projectId: string,
    jobId: string,
    controller: AbortController,
    subscriber: import('rxjs').Subscriber<JobEventResponse>,
    state: { cursor: number; failures: number; seen: Set<number> } = {
      cursor: 0,
      failures: 0,
      seen: new Set<number>(),
    },
  ): Promise<void> {
    while (!controller.signal.aborted) {
      try {
        const token = this.tokens.accessToken();
        if (token === null) {
          subscriber.complete();
          return;
        }
        const url = this.eventUrl(projectId, jobId);
        const response = await this.request(url, {
          credentials: 'include',
          headers: { Authorization: `Bearer ${token}`, 'Last-Event-ID': String(state.cursor) },
          signal: controller.signal,
        });
        if (response.status === 401 && state.failures === 0) {
          state.failures++;
          if ((await firstValueFrom(this.refresh.refresh())) !== null) continue;
        }
        if (!response.ok || response.body === null)
          throw new Error(`SSE request failed (${String(response.status)}).`);
        state.failures = 0;
        for await (const event of parseSse(response.body, controller.signal)) {
          if (state.seen.has(event.sequence) || event.sequence <= state.cursor) continue;
          state.seen.add(event.sequence);
          state.cursor = event.sequence;
          subscriber.next(event);
          if (TERMINAL_STATES.has(event.status)) {
            subscriber.complete();
            return;
          }
        }
        throw new Error('The event stream closed before completion.');
      } catch {
        if (isAborted(controller.signal)) {
          subscriber.complete();
          return;
        }
        state.failures++;
        try {
          const fallback = await this.poll(projectId, jobId, state.cursor, controller.signal);
          for (const event of fallback.events) {
            if (!state.seen.has(event.sequence) && event.sequence > state.cursor) {
              state.seen.add(event.sequence);
              state.cursor = event.sequence;
              subscriber.next(event);
            }
          }
          if (fallback.terminal) {
            subscriber.complete();
            return;
          }
          await delay(Math.min(30_000, 500 * 2 ** Math.min(state.failures, 6)), controller.signal);
        } catch (fallbackError: unknown) {
          if (isAborted(controller.signal)) {
            subscriber.complete();
          } else if (fallbackError instanceof JobEventAuthorizationEndedError) {
            subscriber.complete();
          } else {
            await delay(
              Math.min(30_000, 500 * 2 ** Math.min(state.failures, 6)),
              controller.signal,
            ).catch(() => undefined);
          }
          if (
            isAborted(controller.signal) ||
            fallbackError instanceof JobEventAuthorizationEndedError
          )
            return;
        }
      }
    }
    subscriber.complete();
    this.active.delete(controller);
  }

  private async poll(
    projectId: string,
    jobId: string,
    after: number,
    signal: AbortSignal,
  ): Promise<JobEventPollResponse> {
    const token = this.tokens.accessToken();
    if (token === null) throw new Error('Authentication ended.');
    const response = await this.request(
      this.configuration.buildUrl(
        `/api/v1/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}/events/poll`,
        { after, limit: 100 },
      ),
      { credentials: 'include', headers: { Authorization: `Bearer ${token}` }, signal },
    );
    if ([401, 403, 404].includes(response.status)) throw new JobEventAuthorizationEndedError();
    if (!response.ok) throw new Error(`Event polling failed (${String(response.status)}).`);
    return (await response.json()) as JobEventPollResponse;
  }

  private eventUrl(projectId: string, jobId: string): string {
    return this.configuration.buildSseUrl(
      `/api/v1/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(jobId)}/events`,
    );
  }
}

export async function* parseSse(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<JobEventResponse> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (!signal.aborted) {
      const result = await reader.read();
      buffer += decoder.decode(result.value, { stream: !result.done }).replaceAll('\r\n', '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (data !== '') yield JSON.parse(data) as JobEventResponse;
        boundary = buffer.indexOf('\n\n');
      }
      if (result.done) return;
    }
  } finally {
    reader.releaseLock();
  }
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(resolve, milliseconds);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timeout);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

function isAborted(signal: AbortSignal): boolean {
  return signal.aborted;
}

class JobEventAuthorizationEndedError extends Error {}
