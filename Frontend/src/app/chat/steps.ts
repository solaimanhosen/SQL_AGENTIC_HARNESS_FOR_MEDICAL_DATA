import { Step } from '../api/types';

/** A step as a short phrase for someone waiting on an answer. */
export function describeStep(step: Step): string {
  switch (step.kind) {
    case 'sql':
      return 'Running a query';
    case 'sql_result':
      return `Query finished: ${step.detail}`;
    case 'sql_error':
      return 'A query failed, so the agent is correcting it';
    case 'describe_table':
      return `Reading how ${step.detail} is structured`;
    case 'lookup_definition':
      return `Looking up the definition of ${step.detail}`;
    default:
      return 'Working';
  }
}

/** How many queries have finished so far. */
export function queriesRun(steps: Step[]): number {
  return steps.filter((step) => step.kind === 'sql_result').length;
}
