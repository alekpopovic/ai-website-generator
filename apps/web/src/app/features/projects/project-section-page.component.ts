import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { EmptyStateComponent } from '../../shared/states/empty-state.component';

@Component({
  imports: [EmptyStateComponent],
  template: `
    <section aria-labelledby="project-section-heading">
      <h2 id="project-section-heading" class="visually-hidden">{{ heading() }}</h2>
      <app-empty-state [heading]="heading()" [message]="message()" />
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectSectionPageComponent {
  readonly heading = input.required<string>();
  readonly message = input.required<string>();
}
