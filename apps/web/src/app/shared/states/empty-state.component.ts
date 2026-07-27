import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'app-empty-state',
  template: `
    <div class="state-card empty-state">
      <span class="empty-icon" aria-hidden="true">◇</span>
      <h2>{{ heading() }}</h2>
      <p>{{ message() }}</p>
      <ng-content />
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EmptyStateComponent {
  readonly heading = input.required<string>();
  readonly message = input.required<string>();
}
