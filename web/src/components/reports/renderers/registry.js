import GenericTableRenderer from './GenericTableRenderer';
import KeyValueRenderer from './KeyValueRenderer';

const renderers = new Map([
  ['table', GenericTableRenderer],
  ['key_value', KeyValueRenderer],
]);

export function registerReportRenderer(name, component) {
  renderers.set(name, component);
}

export function getReportRenderer(name) {
  return renderers.get(name) || GenericTableRenderer;
}
