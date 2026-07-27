import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { toAuthenticationError } from '../../core/auth/authentication-error';
import { AuthenticationService } from '../../core/auth/authentication.service';

@Component({
  imports: [RouterLink],
  template: `
    <section class="auth-card" aria-labelledby="verification-heading">
      <p class="eyebrow">Email verification</p>
      <h1 id="verification-heading">Verify your email</h1>
      @if (status() === 'working') {
        <p role="status">Verifying your one-time link…</p>
      } @else if (status() === 'verified') {
        <p role="status">Your email is verified. You can now sign in.</p>
      } @else {
        <p class="field-error" role="alert">{{ message() }}</p>
      }
      <p class="auth-switch"><a routerLink="/login">Go to sign in</a></p>
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VerifyEmailPageComponent {
  private readonly authentication = inject(AuthenticationService);
  private readonly token = tokenFromFragment(inject(ActivatedRoute).snapshot.fragment);
  readonly status = signal<'error' | 'verified' | 'working'>('working');
  readonly message = signal('');

  constructor() {
    void this.verify();
  }

  private async verify(): Promise<void> {
    if (this.token === null) {
      this.status.set('error');
      this.message.set('This verification link is incomplete.');
      return;
    }
    try {
      await this.authentication.verifyEmail(this.token);
      this.status.set('verified');
    } catch (error: unknown) {
      this.status.set('error');
      this.message.set(toAuthenticationError(error).message);
    }
  }
}

function tokenFromFragment(fragment: string | null): string | null {
  return fragment === null ? null : new URLSearchParams(fragment).get('token');
}
