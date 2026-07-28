import { TestBed } from '@angular/core/testing';
import {
  ApiAccessTokenStore,
  PlatformApiConfiguration,
  type JobEventResponse,
} from '@platform/api-client';
import { lastValueFrom, toArray } from 'rxjs';

import {
  JOB_EVENT_FETCH,
  JobEventStreamService,
  parseSse,
  type JobEventFetch,
} from './job-event-stream.service';

describe('JobEventStreamService', () => {
  it('parses split frames, ignores heartbeat comments, and deduplicates sequences', async () => {
    const encoder = new TextEncoder();
    const payload = (sequence: number, status: string) =>
      JSON.stringify({
        id: crypto.randomUUID(),
        job_id: crypto.randomUUID(),
        job_type: 'scan_campaign',
        sequence,
        event_type: 'scan.progress',
        status,
        payload: { completed: sequence },
        created_at: '2026-07-28T00:00:00Z',
      });
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(`: heartbeat\n\nid: 1\ndata: ${payload(1, 'running')}\n`),
        );
        controller.enqueue(
          encoder.encode(
            `\nid: 1\ndata: ${payload(1, 'running')}\n\nid: 2\ndata: ${payload(2, 'succeeded')}\n\n`,
          ),
        );
        controller.close();
      },
    });
    const parsed: JobEventResponse[] = [];
    for await (const event of parseSse(stream, new AbortController().signal)) parsed.push(event);
    expect(parsed.map((event) => event.sequence)).toEqual([1, 1, 2]);

    const request: JobEventFetch = () => Promise.resolve(new Response(streamFrom(parsed)));
    TestBed.configureTestingModule({
      providers: [{ provide: JOB_EVENT_FETCH, useValue: request }],
    });
    TestBed.inject(PlatformApiConfiguration).configure({ baseUrl: 'https://api.example.test' });
    TestBed.inject(ApiAccessTokenStore).set('memory-only-token');
    const events = await lastValueFrom(
      TestBed.inject(JobEventStreamService).watch('p', 'j').pipe(toArray()),
    );
    expect(events.map((event) => event.sequence)).toEqual([1, 2]);
  });
});

function streamFrom(events: readonly object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const event of events)
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      controller.close();
    },
  });
}
