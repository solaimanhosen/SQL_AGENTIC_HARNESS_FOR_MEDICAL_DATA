import { CdkMenu, CdkMenuItemRadio, CdkMenuTrigger } from '@angular/cdk/menu';
import { Component, computed, input, output } from '@angular/core';
import { LucideCheck, LucideChevronDown } from '@lucide/angular';

import { Effort, ModelCatalog, ModelChoice, ModelInfo } from '../api/types';

export const EFFORT_LABELS: Record<Effort, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra high',
  max: 'Max',
};

const EFFORT_HINTS: Record<Effort, string> = {
  low: 'Quickest and cheapest. Fine for simple counts.',
  medium: 'A balance of speed and care.',
  high: 'Careful and thorough. The usual default.',
  xhigh: 'Thinks longer on hard, many-step questions.',
  max: 'As much thinking as the model allows. Slowest.',
};

/** "$5 / $25 per million tokens", from the catalog's base prices. */
export function priceText(model: ModelInfo): string {
  const dollars = (value: number) => `$${value < 1 ? value.toFixed(2) : value.toFixed(0)}`;
  return `${dollars(model.input_price)} / ${dollars(model.output_price)} per million tokens`;
}

/**
 * Two small menus in the question box: which model answers, and how hard it thinks. Each
 * closes when something is picked. The choice applies to the next question, so a conversation
 * can move between models; every answer records the one it came from.
 */
@Component({
  selector: 'app-model-picker',
  imports: [CdkMenu, CdkMenuItemRadio, CdkMenuTrigger, LucideCheck, LucideChevronDown],
  template: `
    @if (current(); as model) {
      <button
        type="button"
        class="ghost pill"
        [cdkMenuTriggerFor]="models"
        [disabled]="disabled()"
        [attr.aria-label]="'Model: ' + model.label"
        title="Choose the model"
      >
        <span>{{ model.label }}</span>
        <svg lucideChevronDown [size]="14"></svg>
      </button>
      <button
        type="button"
        class="ghost pill"
        [cdkMenuTriggerFor]="efforts"
        [disabled]="disabled()"
        [attr.aria-label]="'Effort: ' + effortLabels[choice()!.effort]"
        title="Choose how hard the model thinks"
      >
        <span>{{ effortLabels[choice()!.effort] }} effort</span>
        <svg lucideChevronDown [size]="14"></svg>
      </button>

      <ng-template #models>
        <div class="menu picker-menu" cdkMenu aria-label="Model">
          <p class="menu-label" aria-hidden="true">Model</p>
          @for (option of catalog()!.models; track option.id) {
            <button
              type="button"
              class="menu-item option"
              cdkMenuItemRadio
              [cdkMenuItemChecked]="option.id === model.id"
              (cdkMenuItemTriggered)="pickModel(option)"
            >
              <span class="text">
                <span class="name">{{ option.label }}</span>
                <span class="description">{{ option.description }}</span>
                <span class="facts">
                  {{ price(option) }} ·
                  {{ option.evaluated ? 'Evaluated: ' + option.evaluated : 'Not yet evaluated' }}
                </span>
              </span>
              @if (option.id === model.id) {
                <svg lucideCheck class="check" [size]="16"></svg>
              }
            </button>
          }
        </div>
      </ng-template>

      <ng-template #efforts>
        <div class="menu picker-menu" cdkMenu aria-label="Effort">
          <p class="menu-label" aria-hidden="true">Effort for {{ model.label }}</p>
          @for (level of model.efforts; track level) {
            <button
              type="button"
              class="menu-item option"
              cdkMenuItemRadio
              [cdkMenuItemChecked]="level === choice()!.effort"
              (cdkMenuItemTriggered)="pickEffort(level)"
            >
              <span class="text">
                <span class="name">{{ effortLabels[level] }}</span>
                <span class="description">{{ effortHints[level] }}</span>
              </span>
              @if (level === choice()!.effort) {
                <svg lucideCheck class="check" [size]="16"></svg>
              }
            </button>
          }
        </div>
      </ng-template>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-0-5);
      min-width: 0;
    }
    .pill {
      gap: var(--space-1);
      min-height: var(--control-height-sm);
      padding: 0 var(--space-2);
      border-radius: var(--radius-full);
      font-size: var(--text-xs);
      white-space: nowrap;
    }
    .picker-menu {
      width: min(22rem, calc(100vw - 2 * var(--space-4)));
    }
    .option {
      align-items: flex-start;
      min-height: 0;
      padding: var(--space-2);
    }
    .text {
      display: grid;
      flex: 1;
      gap: var(--space-0-5);
      min-width: 0;
    }
    .name {
      font-weight: var(--weight-medium);
    }
    .description {
      color: var(--text-muted);
      font-size: var(--text-xs);
      line-height: var(--leading-tight);
      white-space: normal;
    }
    .facts {
      color: var(--text-subtle);
      font-size: 0.6875rem;
      font-variant-numeric: tabular-nums;
      white-space: normal;
    }
    .check {
      margin-top: var(--space-0-5);
    }
  `,
})
export class ModelPicker {
  readonly catalog = input<ModelCatalog | null>(null);
  readonly choice = input<ModelChoice | null>(null);
  /** True while an answer is being written: the next question cannot be asked yet anyway. */
  readonly disabled = input(false);
  readonly choiceChange = output<ModelChoice>();

  protected readonly effortLabels = EFFORT_LABELS;
  protected readonly effortHints = EFFORT_HINTS;
  protected readonly price = priceText;

  protected readonly current = computed(() => {
    const choice = this.choice();
    return this.catalog()?.models.find((model) => model.id === choice?.model) ?? null;
  });

  /**
   * A new model keeps the effort if it offers it, and otherwise takes its own default. The
   * effort is a separate choice, so switching model does not quietly reset it.
   */
  protected pickModel(model: ModelInfo): void {
    const effort = this.choice()?.effort;
    this.choiceChange.emit({
      model: model.id,
      effort: effort && model.efforts.includes(effort) ? effort : model.default_effort,
    });
  }

  protected pickEffort(effort: Effort): void {
    this.choiceChange.emit({ model: this.choice()!.model, effort });
  }
}
