import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import {
  ApiAccessTokenStore,
  Auth,
  type ApiRefreshStrategy,
  type LoginRequest,
  type PasswordResetRequest,
  type RegisterRequest,
  type ResetPasswordRequest,
  type UserResponse,
} from '@platform/api-client';
import { Observable, from } from 'rxjs';

import { toAuthenticationError } from './authentication-error';
import { JobEventStreamService } from '../job-events/job-event-stream.service';

@Injectable({ providedIn: 'root' })
export class AuthenticationService implements ApiRefreshStrategy {
  private readonly api = inject(Auth);
  private readonly tokens = inject(ApiAccessTokenStore);
  private readonly router = inject(Router);
  private readonly jobEvents = inject(JobEventStreamService);
  private readonly currentUserValue = signal<UserResponse | null>(null);
  private initialized = false;

  readonly currentUser = this.currentUserValue.asReadonly();
  readonly authenticated = () => this.currentUserValue() !== null;

  async initialize(): Promise<void> {
    if (this.initialized) return;
    this.initialized = true;
    const accessToken = await this.refreshInternal();
    if (accessToken === null) return;
    const result = await this.api.getCurrentUser();
    if (result.error !== undefined) {
      this.clearSession();
      return;
    }
    this.currentUserValue.set(result.data);
  }

  async login(payload: LoginRequest): Promise<void> {
    const result = await this.api.login({ body: payload });
    if (result.error !== undefined) throw toAuthenticationError(result.error);
    this.tokens.set(result.data.access_token);
    this.currentUserValue.set(result.data.user);
  }

  async register(payload: RegisterRequest): Promise<UserResponse> {
    const result = await this.api.register({ body: payload });
    if (result.error !== undefined) throw toAuthenticationError(result.error);
    return result.data;
  }

  async requestPasswordReset(payload: PasswordResetRequest): Promise<void> {
    const result = await this.api.requestPasswordReset({ body: payload });
    if (result.error !== undefined) throw toAuthenticationError(result.error);
  }

  async resetPassword(payload: ResetPasswordRequest): Promise<void> {
    const result = await this.api.resetPassword({ body: payload });
    if (result.error !== undefined) throw toAuthenticationError(result.error);
  }

  async verifyEmail(token: string): Promise<void> {
    const result = await this.api.verifyEmail({ body: { token } });
    if (result.error !== undefined) throw toAuthenticationError(result.error);
  }

  refreshAccessToken(): Observable<string | null> {
    return from(this.refreshInternal());
  }

  async logout(): Promise<void> {
    try {
      await this.api.logout();
    } finally {
      this.clearSession();
      await this.router.navigateByUrl('/login');
    }
  }

  async logoutAll(): Promise<void> {
    try {
      await this.api.logoutAll();
    } finally {
      this.clearSession();
      await this.router.navigateByUrl('/login');
    }
  }

  clearSession(): void {
    this.jobEvents.closeAll();
    this.tokens.clear();
    this.currentUserValue.set(null);
  }

  private async refreshInternal(): Promise<string | null> {
    const result = await this.api.refreshAccessToken();
    if (result.error !== undefined) {
      this.clearSession();
      return null;
    }
    this.tokens.set(result.data.access_token);
    this.currentUserValue.set(result.data.user);
    return result.data.access_token;
  }
}
