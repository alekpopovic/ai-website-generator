import type { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: 'login',
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
    path: '',
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
