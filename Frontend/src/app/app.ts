import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { Theme } from './ui/theme';

/** The root: every screen is a route. The theme is started here so it applies to all of them. */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  template: '<router-outlet />',
  styles: ':host { display: contents; }',
})
export class App {
  constructor() {
    inject(Theme);
  }
}
