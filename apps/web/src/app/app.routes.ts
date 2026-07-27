import type { Routes } from '@angular/router';

import { environment } from '../environments/environment';
import { authenticationGuard, publicOnlyGuard } from './core/auth/authentication.guard';

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [publicOnlyGuard],
    loadComponent: () =>
      import('./layouts/public-layout/public-layout.component').then(
        (module) => module.PublicLayoutComponent,
      ),
    children: [
      {
        path: '',
        title: 'Sign in',
        loadComponent: () =>
          import('./features/login/login-page.component').then(
            (module) => module.LoginPageComponent,
          ),
      },
    ],
  },
  {
    path: 'register',
    canActivate: [publicOnlyGuard],
    loadComponent: () =>
      import('./layouts/public-layout/public-layout.component').then(
        (module) => module.PublicLayoutComponent,
      ),
    children: [
      {
        path: '',
        title: 'Create account',
        loadComponent: () =>
          import('./features/register/register-page.component').then(
            (module) => module.RegisterPageComponent,
          ),
      },
    ],
  },
  {
    path: '',
    loadComponent: () =>
      import('./layouts/public-layout/public-layout.component').then(
        (module) => module.PublicLayoutComponent,
      ),
    children: [
      {
        path: 'request-password-reset',
        title: 'Reset password',
        loadComponent: () =>
          import('./features/password-reset/request-password-reset-page.component').then(
            (module) => module.RequestPasswordResetPageComponent,
          ),
      },
      {
        path: 'reset-password',
        title: 'Choose a new password',
        loadComponent: () =>
          import('./features/password-reset/reset-password-page.component').then(
            (module) => module.ResetPasswordPageComponent,
          ),
      },
      {
        path: 'verify-email',
        title: 'Verify email',
        loadComponent: () =>
          import('./features/email-verification/verify-email-page.component').then(
            (module) => module.VerifyEmailPageComponent,
          ),
      },
    ],
  },
  {
    path: '',
    canActivate: [authenticationGuard],
    loadComponent: () =>
      import('./layouts/authenticated-layout/authenticated-layout.component').then(
        (module) => module.AuthenticatedLayoutComponent,
      ),
    children: [
      featureRoute('dashboard', 'Dashboard', 'Monitor platform work and recent activity.'),
      featureRoute('projects', 'Projects', 'Create and manage website generation projects.'),
      featureRoute('scanner', 'Scanner', 'Configure authorized website discovery and scanning.'),
      featureRoute('datasets', 'Datasets', 'Review governed datasets and their provenance.'),
      featureRoute('models', 'Models', 'Review configured inference and embedding models.'),
      featureRoute(
        'generator',
        'Generator',
        'Create sites from validated structured specifications.',
      ),
      featureRoute('settings', 'Settings', 'Manage workspace and application preferences.'),
      ...developerRoutes(),
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
    ],
  },
  {
    path: '**',
    title: 'Page not found',
    loadComponent: () =>
      import('./features/not-found/not-found-page.component').then(
        (module) => module.NotFoundPageComponent,
      ),
  },
];

function featureRoute(path: string, title: string, description: string): Routes[number] {
  return {
    path,
    title,
    data: { heading: title, description },
    loadComponent: () =>
      import('./features/feature-entry/feature-entry-page.component').then(
        (module) => module.FeatureEntryPageComponent,
      ),
  };
}

function developerRoutes(): Routes {
  return environment.production
    ? []
    : [
        {
          path: 'diagnostics',
          title: 'API diagnostics',
          loadComponent: () =>
            import('./features/diagnostics/diagnostics-page.component').then(
              (module) => module.DiagnosticsPageComponent,
            ),
        },
      ];
}
