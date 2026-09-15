import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import FormField from '../components/ui/FormField';

describe('FormField', () => {
  it('wires the label to the control via htmlFor', () => {
    render(
      <FormField label="任务名称" htmlFor="task-name">
        <input id="task-name" />
      </FormField>,
    );
    expect(screen.getByText('任务名称')).toHaveAttribute('for', 'task-name');
    expect(screen.getByLabelText('任务名称')).toBeInTheDocument();
  });

  it('renders the required mark next to the label', () => {
    render(
      <FormField label="任务名称" required>
        <input />
      </FormField>,
    );
    expect(screen.getByText('*')).toHaveAttribute('aria-hidden', 'true');
  });

  it('shows the error with role=alert instead of the hint', () => {
    render(
      <FormField label="端口" error="端口必须为正数" hint="默认 8080">
        <input />
      </FormField>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('端口必须为正数');
    expect(screen.queryByText('默认 8080')).not.toBeInTheDocument();
  });

  it('shows the hint when there is no error', () => {
    render(
      <FormField label="端口" hint="默认 8080">
        <input />
      </FormField>,
    );
    expect(screen.getByText('默认 8080')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('renders neither hint nor error when neither is given', () => {
    const { container } = render(
      <FormField label="备注">
        <input />
      </FormField>,
    );
    expect(container.querySelector('p')).toBeNull();
  });

  it('renders the wrapped control', () => {
    render(
      <FormField label="名称">
        <input aria-label="名称" />
      </FormField>,
    );
    expect(screen.getByLabelText('名称')).toBeInTheDocument();
  });
});
