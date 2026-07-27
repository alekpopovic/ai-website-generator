import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { FormFieldComponent } from '../../shared/forms/form-field.component';
import { NotificationService } from '../../core/notifications/notification.service';

@Component({
  imports: [ReactiveFormsModule, FormFieldComponent],
  template: `
    <section class="auth-card" aria-labelledby="login-heading">
      <p class="eyebrow">Control plane</p>
      <h1 id="login-heading">Sign in</h1>
      <p>Authentication will be connected in a later implementation step.</p>

      <form class="form-stack" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <app-form-field
          label="Email address"
          controlId="email"
          hint="Use your workspace email address."
          [error]="emailError"
        >
          <input
            id="email"
            class="text-input"
            type="email"
            inputmode="email"
            autocomplete="email"
            formControlName="email"
            [attr.aria-invalid]="form.controls.email.invalid && form.controls.email.touched"
            [attr.aria-describedby]="'email-hint email-error'"
          />
        </app-form-field>
        <app-form-field label="Password" controlId="password" [error]="passwordError">
          <input
            id="password"
            class="text-input"
            type="password"
            autocomplete="current-password"
            formControlName="password"
            [attr.aria-invalid]="form.controls.password.invalid && form.controls.password.touched"
            aria-describedby="password-error"
          />
        </app-form-field>
        <button class="primary-button" type="submit">Continue</button>
      </form>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPageComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly notifications = inject(NotificationService);

  readonly form = this.formBuilder.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  get emailError(): string | null {
    const control = this.form.controls.email;
    if (!control.touched || control.valid) return null;
    return control.hasError('required') ? 'Email is required.' : 'Enter a valid email address.';
  }

  get passwordError(): string | null {
    const control = this.form.controls.password;
    return control.touched && control.invalid ? 'Password is required.' : null;
  }

  submit(): void {
    this.form.markAllAsTouched();
    if (this.form.valid) {
      this.notifications.info('Authentication is not connected yet.');
    }
  }
}
