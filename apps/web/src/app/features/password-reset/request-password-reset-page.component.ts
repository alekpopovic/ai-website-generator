import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { toAuthenticationError } from '../../core/auth/authentication-error';
import { AuthenticationService } from '../../core/auth/authentication.service';
import { FormFieldComponent } from '../../shared/forms/form-field.component';

@Component({
  imports: [ReactiveFormsModule, RouterLink, FormFieldComponent],
  template: `
    <section class="auth-card" aria-labelledby="reset-request-heading">
      <p class="eyebrow">Account recovery</p>
      <h1 id="reset-request-heading">Reset your password</h1>
      <p>Enter your email address. If it matches an account, we will send a one-time link.</p>
      @if (submitted()) {
        <p role="status">Check your inbox for the next step.</p>
      } @else {
        <form class="form-stack" [formGroup]="form" (ngSubmit)="submit()" novalidate>
          <app-form-field label="Email address" controlId="reset-email" [error]="emailError">
            <input
              id="reset-email"
              class="text-input"
              type="email"
              autocomplete="email"
              formControlName="email"
            />
          </app-form-field>
          @if (formError()) {
            <p class="field-error" role="alert">{{ formError() }}</p>
          }
          <button class="primary-button" type="submit" [disabled]="submitting()">
            {{ submitting() ? 'Sending…' : 'Send reset link' }}
          </button>
        </form>
      }
      <p class="auth-switch"><a routerLink="/login">Back to sign in</a></p>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RequestPasswordResetPageComponent {
  private readonly authentication = inject(AuthenticationService);
  private readonly formBuilder = inject(FormBuilder);
  readonly submitting = signal(false);
  readonly submitted = signal(false);
  readonly formError = signal<string | null>(null);
  readonly form = this.formBuilder.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
  });

  get emailError(): string | null {
    const control = this.form.controls.email;
    if (!control.touched || control.valid) return null;
    return control.hasError('required') ? 'Email is required.' : 'Enter a valid email address.';
  }

  async submit(): Promise<void> {
    this.form.markAllAsTouched();
    if (this.form.invalid || this.submitting()) return;
    this.submitting.set(true);
    this.formError.set(null);
    try {
      await this.authentication.requestPasswordReset(this.form.getRawValue());
      this.submitted.set(true);
    } catch (error: unknown) {
      this.formError.set(toAuthenticationError(error).message);
    } finally {
      this.submitting.set(false);
    }
  }
}
