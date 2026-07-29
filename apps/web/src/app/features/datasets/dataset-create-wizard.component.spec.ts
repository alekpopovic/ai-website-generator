import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';

import { DatasetApiService } from '../../core/datasets/dataset-api.service';
import { DatasetCreateWizardComponent } from './dataset-create-wizard.component';

describe('DatasetCreateWizardComponent', () => {
  it('creates a dataset and its first draft from the accessible wizard', async () => {
    const api = {
      create: vi.fn().mockResolvedValue({ id: 'dataset-id' }),
      createVersion: vi.fn().mockResolvedValue({ id: 'version-id' }),
    };
    const router = { navigate: vi.fn().mockResolvedValue(true) };
    await TestBed.configureTestingModule({
      imports: [DatasetCreateWizardComponent],
      providers: [
        { provide: DatasetApiService, useValue: api },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: new Map([['projectId', 'project-id']]) },
          },
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DatasetCreateWizardComponent);
    fixture.detectChanges();
    const component = fixture.componentInstance;
    component.form.patchValue({
      name: 'Curated layouts',
      purpose: 'Train layout selection',
      categories: 'Homepage, Pricing',
      languages: 'EN',
    });
    component.next();
    component.next();
    await component.submit();

    expect(api.create).toHaveBeenCalledWith(
      'project-id',
      expect.objectContaining({
        name: 'Curated layouts',
        category_filters: ['homepage', 'pricing'],
        language_filters: ['en'],
        require_approved: true,
      }),
    );
    expect(api.createVersion).toHaveBeenCalledWith('project-id', 'dataset-id');
    expect(router.navigate).toHaveBeenCalled();
  });
});
