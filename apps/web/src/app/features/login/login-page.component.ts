import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { toAuthenticationError } from '../../core/auth/authentication-error';
import { AuthenticationService } from '../../core/auth/authentication.service';
import { FormFieldComponent } from '../../shared/forms/form-field.component';
import { NotificationService } from '../../core/notifications/notification.service';

@Component({
  imports: [ReactiveFormsModule, RouterLink, FormFieldComponent],
  template: `
    <section class="auth-card" aria-labelledby="login-heading">
      <p class="eyebrow">Control plane</p>
      <h1 id="login-heading">Sign in</h1>
      <p>Use your verified email address to continue.</p>

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
        @if (formError()) {
          <p class="field-error" role="alert">{{ formError() }}</p>
        }
        <button class="primary-button" type="submit" [disabled]="submitting()">
          {{ submitting() ? 'Signing in…' : 'Continue' }}
        </button>
      </form>
      <p class="auth-switch"><a routerLink="/request-password-reset">Forgot password?</a></p>
      <p class="auth-switch">New here? <a routerLink="/register">Create an account</a>.</p>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPageComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly notifications = inject(NotificationService);
  private readonly authentication = inject(AuthenticationService);
  private readonly router = inject(Router);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

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

  async submit(): Promise<void> {
    this.form.markAllAsTouched();
    if (this.form.invalid || this.submitting()) return;
    this.submitting.set(true);
    this.formError.set(null);
    try {
      await this.authentication.login(this.form.getRawValue());
      this.notifications.success('Signed in successfully.');
      await this.router.navigateByUrl('/dashboard');
    } catch (error: unknown) {
      const authenticationError = toAuthenticationError(error);
      const emailError = authenticationError.fieldError('email');
      const passwordError = authenticationError.fieldError('password');
      if (emailError !== null) this.form.controls.email.setErrors({ server: emailError });
      if (passwordError !== null) this.form.controls.password.setErrors({ server: passwordError });
      this.formError.set(authenticationError.message);
    } finally {
      this.submitting.set(false);
    }
  }
}
