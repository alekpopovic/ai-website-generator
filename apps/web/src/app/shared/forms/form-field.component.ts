import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'app-form-field',
  template: `
    <div class="form-field">
      <label class="field-label" [for]="controlId()">{{ label() }}</label>
      <ng-content />
      @if (hint()) {
        <p class="field-hint" [id]="controlId() + '-hint'">{{ hint() }}</p>
      }
      @if (error(); as errorMessage) {
        <p class="field-error" [id]="controlId() + '-error'" role="alert">
          {{ errorMessage }}
        </p>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FormFieldComponent {
  readonly label = input.required<string>();
  readonly controlId = input.required<string>();
  readonly hint = input<string | null>(null);
  readonly error = input<string | null>(null);
}
