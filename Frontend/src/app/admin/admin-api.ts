import { Injectable, inject } from '@angular/core';

import { AgentApi } from '../api/agent-api';
import { AdminMetrics, AdminOverview, AdminUser, JobInfo, RunRecord } from '../api/admin-types';
import { SseParser } from '../api/sse';

/** One event while following a run: a line of output, or the finished record. */
export type RunEvent = { type: 'line'; text: string } | { type: 'done'; run: RunRecord };

/**
 * The admin console's calls. They go through AgentApi's request, so they carry the same
 * application header and report an ended session the same way.
 */
@Injectable({ providedIn: 'root' })
export class AdminApi {
  private readonly api = inject(AgentApi);

  overview(): Promise<AdminOverview> {
    return this.api.json('/admin/overview', 'GET');
  }

  metrics(days: number): Promise<AdminMetrics> {
    return this.api.json(`/admin/metrics?days=${days}`, 'GET');
  }

  jobs(): Promise<JobInfo[]> {
    return this.api.json('/admin/jobs', 'GET');
  }

  startRun(job: string, choices: Record<string, string> = {}): Promise<RunRecord> {
    return this.api.json(`/admin/jobs/${encodeURIComponent(job)}/runs`, 'POST', { choices });
  }

  runs(job?: string): Promise<RunRecord[]> {
    return this.api.json(job ? `/admin/runs?job=${encodeURIComponent(job)}` : '/admin/runs', 'GET');
  }

  run(id: string): Promise<RunRecord> {
    return this.api.json(`/admin/runs/${encodeURIComponent(id)}`, 'GET');
  }

  cancelRun(id: string): Promise<{ cancelling: boolean }> {
    return this.api.json(`/admin/runs/${encodeURIComponent(id)}/cancel`, 'POST');
  }

  /** The run's output as it is written, then its record. Stops when the run is done. */
  async *follow(id: string, abort?: AbortSignal): AsyncGenerator<RunEvent> {
    const response = await this.api.request(`/admin/runs/${encodeURIComponent(id)}/stream`, {
      method: 'GET',
      headers: { Accept: 'text/event-stream' },
      signal: abort,
    });
    if (!response.body) {
      return;
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    const parser = new SseParser();
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          return;
        }
        for (const message of parser.push(value)) {
          const data = JSON.parse(message.data);
          if (message.event === 'line') {
            yield { type: 'line', text: String(data.text ?? '') };
          } else if (message.event === 'done') {
            yield { type: 'done', run: data as RunRecord };
            return;
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  users(): Promise<AdminUser[]> {
    return this.api.json('/admin/users', 'GET');
  }

  changeUser(id: string, changes: { role?: 'user' | 'admin'; disabled?: boolean }) {
    return this.api.json<{ id: string; role: string; disabled: boolean }>(
      `/admin/users/${encodeURIComponent(id)}`,
      'PATCH',
      changes,
    );
  }

  resetPassword(id: string): Promise<{ temporary_password: string }> {
    return this.api.json(`/admin/users/${encodeURIComponent(id)}/reset-password`, 'POST');
  }

  settings(): Promise<{ registration_open: boolean }> {
    return this.api.json('/admin/settings', 'GET');
  }

  changeSettings(registrationOpen: boolean): Promise<{ registration_open: boolean }> {
    return this.api.json('/admin/settings', 'PATCH', { registration_open: registrationOpen });
  }
}
