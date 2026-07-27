import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { EmptyStateComponent } from '../../shared/states/empty-state.component';

@Component({
  imports: [EmptyStateComponent],
  template: `
    <section class="page-stack" aria-labelledby="page-heading">
      <header class="page-header">
        <div>
          <p class="eyebrow">Workspace</p>
          <h1 id="page-heading">{{ heading() }}</h1>
          <p>{{ description() }}</p>
        </div>
      </header>
      <app-empty-state
        heading="Nothing here yet"
        message="This area is ready for its feature implementation."
      />
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FeatureEntryPageComponent {
  readonly heading = input.required<string>();
  readonly description = input.required<string>();
}
