import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { toAuthenticationError } from '../../core/auth/authentication-error';
import { AuthenticationService } from '../../core/auth/authentication.service';
import { NotificationService } from '../../core/notifications/notification.service';
import { FormFieldComponent } from '../../shared/forms/form-field.component';

@Component({
  imports: [ReactiveFormsModule, RouterLink, FormFieldComponent],
  template: `
    <section class="auth-card" aria-labelledby="reset-heading">
      <p class="eyebrow">Account recovery</p>
      <h1 id="reset-heading">Choose a new password</h1>
      <form class="form-stack" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <app-form-field
          label="New password"
          controlId="new-password"
          hint="Use at least 12 characters with uppercase, lowercase, number, and symbol."
          [error]="fieldError('password')"
        >
          <input
            id="new-password"
            class="text-input"
            type="password"
            autocomplete="new-password"
            formControlName="password"
          />
        </app-form-field>
        <app-form-field
          label="Confirm password"
          controlId="reset-confirm-password"
          [error]="fieldError('confirmation')"
        >
          <input
            id="reset-confirm-password"
            class="text-input"
            type="password"
            autocomplete="new-password"
            formControlName="confirmation"
          />
        </app-form-field>
        @if (formError()) {
          <p class="field-error" role="alert">{{ formError() }}</p>
        }
        <button class="primary-button" type="submit" [disabled]="submitting() || token === null">
          {{ submitting() ? 'Updating…' : 'Update password' }}
        </button>
      </form>
      <p class="auth-switch"><a routerLink="/login">Back to sign in</a></p>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ResetPasswordPageComponent {
  private readonly authentication = inject(AuthenticationService);
  private readonly notifications = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly formBuilder = inject(FormBuilder);
  readonly token = tokenFromFragment(inject(ActivatedRoute).snapshot.fragment);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(
    this.token === null ? 'This reset link is incomplete.' : null,
  );
  readonly form = this.formBuilder.nonNullable.group({
    password: ['', [Validators.required, Validators.minLength(12), Validators.maxLength(128)]],
    confirmation: ['', [Validators.required]],
  });

  fieldError(name: keyof typeof this.form.controls): string | null {
    const control = this.form.controls[name];
    if (!control.touched || control.valid) return null;
    if (control.hasError('required')) return 'This field is required.';
    if (control.hasError('minlength')) return 'Use at least 12 characters.';
    if (control.hasError('passwordMismatch')) return 'Passwords do not match.';
    return 'Check this value.';
  }

  async submit(): Promise<void> {
    this.form.markAllAsTouched();
    if (this.form.controls.password.value !== this.form.controls.confirmation.value) {
      this.form.controls.confirmation.setErrors({ passwordMismatch: true });
    }
    if (this.form.invalid || this.submitting() || this.token === null) return;
    this.submitting.set(true);
    this.formError.set(null);
    try {
      await this.authentication.resetPassword({
        token: this.token,
        password: this.form.controls.password.value,
      });
      this.notifications.success('Password updated. Sign in with your new password.');
      await this.router.navigateByUrl('/login');
    } catch (error: unknown) {
      this.formError.set(toAuthenticationError(error).message);
    } finally {
      this.submitting.set(false);
    }
  }
}

function tokenFromFragment(fragment: string | null): string | null {
  return fragment === null ? null : new URLSearchParams(fragment).get('token');
}
