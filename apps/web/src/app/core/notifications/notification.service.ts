import { LiveAnnouncer } from '@angular/cdk/a11y';
import { Injectable, inject, signal } from '@angular/core';

export type NotificationTone = 'error' | 'info' | 'success';

export interface AppNotification {
  readonly id: number;
  readonly message: string;
  readonly tone: NotificationTone;
}

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly liveAnnouncer = inject(LiveAnnouncer);
  private nextId = 1;
  readonly items = signal<readonly AppNotification[]>([]);

  error(message: string): void {
    this.add(message, 'error');
  }

  info(message: string): void {
    this.add(message, 'info');
  }

  success(message: string): void {
    this.add(message, 'success');
  }

  dismiss(id: number): void {
    this.items.update((items) => items.filter((item) => item.id !== id));
  }

  private add(message: string, tone: NotificationTone): void {
    const item: AppNotification = { id: this.nextId++, message, tone };
    this.items.update((items) => [...items, item]);
    void this.liveAnnouncer.announce(message, tone === 'error' ? 'assertive' : 'polite');
  }
}
