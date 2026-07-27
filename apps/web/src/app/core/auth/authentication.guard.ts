import { inject } from '@angular/core';
import type { CanActivateFn } from '@angular/router';
import { Router } from '@angular/router';

import { AuthenticationService } from './authentication.service';

export const authenticationGuard: CanActivateFn = async () => {
  const authentication = inject(AuthenticationService);
  const router = inject(Router);
  await authentication.initialize();
  return authentication.authenticated() ? true : router.createUrlTree(['/login']);
};

export const publicOnlyGuard: CanActivateFn = async () => {
  const authentication = inject(AuthenticationService);
  const router = inject(Router);
  await authentication.initialize();
  return authentication.authenticated() ? router.createUrlTree(['/dashboard']) : true;
};
