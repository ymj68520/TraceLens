import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import store from '../store';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import { formatBytes, truncate } from '../lib/utils';

describe('utils', () => {
  it('formatBytes handles edge cases', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatBytes(null)).toBe('—');
    expect(formatBytes(undefined)).toBe('—');
  });

  it('truncate caps long strings', () => {
    expect(truncate('short', 10)).toBe('short');
    expect(truncate('a'.repeat(100), 10)).toHaveLength(10);
  });
});

describe('ui primitives', () => {
  it('Badge renders children', () => {
    render(<Badge tone="success">ok</Badge>);
    expect(screen.getByText('ok')).toBeInTheDocument();
  });

  it('Button is disabled when told to be', () => {
    render(<Button disabled>save</Button>);
    expect(screen.getByRole('button', { name: 'save' })).toBeDisabled();
  });
});

describe('store', () => {
  it('has the expected slice keys', () => {
    const state = store.getState();
    expect(state).toHaveProperty('tasks');
    expect(state).toHaveProperty('cases');
    expect(state).toHaveProperty('settings');
    expect(state).toHaveProperty('intelligence');
    expect(state).toHaveProperty('filter');
  });
});
