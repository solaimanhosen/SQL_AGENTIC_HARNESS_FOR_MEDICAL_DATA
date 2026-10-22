import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';

import { routes } from './app.routes';

/** The router as the app uses it, shared with the tests so they route the same way. */
export function provideAppRouter() {
  // Route parameters, such as the conversation id, arrive as component inputs.
  return provideRouter(routes, withComponentInputBinding());
}

export const appConfig: ApplicationConfig = {
  providers: [provideBrowserGlobalErrorListeners(), provideAppRouter()],
};
