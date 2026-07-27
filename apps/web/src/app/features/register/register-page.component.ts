import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import type { RegisterRequest } from '@platform/api-client';

import { toAuthenticationError } from '../../core/auth/authentication-error';
import { AuthenticationService } from '../../core/auth/authentication.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { FormFieldComponent } from '../../shared/forms/form-field.component';

@Component({
  imports: [ReactiveFormsModule, RouterLink, FormFieldComponent],
  template: `
    <section class="auth-card" aria-labelledby="register-heading">
      <p class="eyebrow">Control plane</p>
      <h1 id="register-heading">Create account</h1>
      <p>We will send a verification link before your first sign-in.</p>

      <form class="form-stack" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <app-form-field
          label="Display name"
          controlId="display-name"
          [error]="fieldError('displayName')"
        >
          <input
            id="display-name"
            class="text-input"
            autocomplete="name"
            formControlName="displayName"
          />
        </app-form-field>
        <app-form-field
          label="Email address"
          controlId="register-email"
          [error]="fieldError('email')"
        >
          <input
            id="register-email"
            class="text-input"
            type="email"
            inputmode="email"
            autocomplete="email"
            formControlName="email"
          />
        </app-form-field>
        <app-form-field
          label="Password"
          controlId="register-password"
          hint="Use at least 12 characters with uppercase, lowercase, number, and symbol."
          [error]="fieldError('password')"
        >
          <input
            id="register-password"
            class="text-input"
            type="password"
            autocomplete="new-password"
            formControlName="password"
          />
        </app-form-field>
        <app-form-field
          label="Confirm password"
          controlId="confirm-password"
          [error]="fieldError('confirmPassword')"
        >
          <input
            id="confirm-password"
            class="text-input"
            type="password"
            autocomplete="new-password"
            formControlName="confirmPassword"
          />
        </app-form-field>
        @if (formError()) {
          <p class="field-error" role="alert">{{ formError() }}</p>
        }
        <button class="primary-button" type="submit" [disabled]="submitting()">
          {{ submitting() ? 'Creating account…' : 'Create account' }}
        </button>
      </form>
      <p class="auth-switch">Already registered? <a routerLink="/login">Sign in</a>.</p>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RegisterPageComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly authentication = inject(AuthenticationService);
  private readonly notifications = inject(NotificationService);
  private readonly router = inject(Router);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  readonly form = this.formBuilder.nonNullable.group({
    displayName: ['', [Validators.required, Validators.maxLength(200)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(12), Validators.maxLength(128)]],
    confirmPassword: ['', [Validators.required]],
  });

  fieldError(name: keyof typeof this.form.controls): string | null {
    const control = this.form.controls[name];
    if (!control.touched || control.valid) return null;
    const server: unknown = control.getError('server');
    if (typeof server === 'string') return server;
    if (control.hasError('required')) return 'This field is required.';
    if (control.hasError('email')) return 'Enter a valid email address.';
    if (control.hasError('minlength')) return 'Use at least 12 characters.';
    if (control.hasError('maxlength')) return 'This value is too long.';
    if (control.hasError('passwordMismatch')) return 'Passwords do not match.';
    return 'Check this value.';
  }

  async submit(): Promise<void> {
    this.form.markAllAsTouched();
    if (this.form.controls.password.value !== this.form.controls.confirmPassword.value) {
      this.form.controls.confirmPassword.setErrors({ passwordMismatch: true });
    }
    if (this.form.invalid || this.submitting()) return;
    this.submitting.set(true);
    this.formError.set(null);
    const value = this.form.getRawValue();
    const payload: RegisterRequest = {
      display_name: value.displayName,
      email: value.email,
      password: value.password,
    };
    try {
      await this.authentication.register(payload);
      this.notifications.success('Account created. Check your email to verify it.');
      await this.router.navigateByUrl('/login');
    } catch (error: unknown) {
      const authenticationError = toAuthenticationError(error);
      this.applyServerError('displayName', authenticationError.fieldError('display_name'));
      this.applyServerError('email', authenticationError.fieldError('email'));
      this.applyServerError('password', authenticationError.fieldError('password'));
      this.formError.set(authenticationError.message);
    } finally {
      this.submitting.set(false);
    }
  }

  private applyServerError(
    control: 'displayName' | 'email' | 'password',
    message: string | null,
  ): void {
    if (message !== null) this.form.controls[control].setErrors({ server: message });
  }
}
