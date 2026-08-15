import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { useInvestigationGraph } from './useInvestigationGraph';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

function graphResponse(overrides = {}) {
  return {
    task_id: 'task-1',
    base_graph_available: true,
    base_max_nodes: 200,
    nodes: [
      { id: 'event:e1', name: 'Event One', label: 'InvestigationEvent', source: 'investigation', confirmed: null, provenance: { event_id: 'e1', version: 2 } },
      { id: 'base-uuid-1', name: 'Base Entity', label: 'Entity', source: 'base_kg' },
    ],
    links: [
      { id: 'event_evidence:e1:file:/a', source: 'event:e1', target: 'evidence:file:/a', label: 'LINKS_EVIDENCE', kind: 'event_evidence' },
    ],
    warnings: [],
    ...overrides,
  };
}

describe('useInvestigationGraph', () => {
  test('loads the graph for the current task and normalizes the response', async () => {
    const fetchGraph = vi.fn().mockResolvedValue(graphResponse());
    const { result } = renderHook(() =>
      useInvestigationGraph({ taskId: 'task-1', fetchGraph }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchGraph).toHaveBeenCalledWith('task-1', { maxBaseNodes: 200 });
    expect(result.current.error).toBeNull();
    expect(result.current.graph.nodes).toHaveLength(2);
    expect(result.current.graph.links).toHaveLength(1);
    expect(result.current.graph.base_graph_available).toBe(true);
  });

  test('exposes loading while the request is pending', async () => {
    const pending = deferred();
    const fetchGraph = vi.fn().mockReturnValue(pending.promise);
    const { result } = renderHook(() =>
      useInvestigationGraph({ taskId: 'task-1', fetchGraph }),
    );

    expect(result.current.loading).toBe(true);
    await act(async () => pending.resolve(graphResponse()));
    expect(result.current.loading).toBe(false);
  });

  test('ignores a stale response that resolves after the task switched', async () => {
    const taskADeferred = deferred();
    const taskBDeferred = deferred();
    const fetchGraph = vi
      .fn()
      .mockReturnValueOnce(taskADeferred.promise)
      .mockReturnValueOnce(taskBDeferred.promise);
    const { result, rerender } = renderHook(
      ({ taskId }) => useInvestigationGraph({ taskId, fetchGraph }),
      { initialProps: { taskId: 'task-a' } },
    );

    await act(async () => {
      // GUI1->GUI2: switch to task B while task A's request is pending.
      rerender({ taskId: 'task-b' });
      // GUI3: task B resolves first.
      taskBDeferred.resolve(graphResponse({ task_id: 'task-b' }));
    });
    await waitFor(() => expect(result.current.graph.task_id).toBe('task-b'));

    // Task A returns late: it must never overwrite task B's graph.
    await act(async () => {
      taskADeferred.resolve(graphResponse({ task_id: 'task-a' }));
    });
    expect(result.current.graph.task_id).toBe('task-b');
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  test('ignores a stale rejection that happens after the task switched', async () => {
    const taskADeferred = deferred();
    const taskBDeferred = deferred();
    const fetchGraph = vi
      .fn()
      .mockReturnValueOnce(taskADeferred.promise)
      .mockReturnValueOnce(taskBDeferred.promise);
    const { result, rerender } = renderHook(
      ({ taskId }) => useInvestigationGraph({ taskId, fetchGraph }),
      { initialProps: { taskId: 'task-a' } },
    );

    await act(async () => {
      rerender({ taskId: 'task-b' });
      taskBDeferred.resolve(graphResponse({ task_id: 'task-b' }));
    });
    await waitFor(() => expect(result.current.graph.task_id).toBe('task-b'));

    await act(async () => {
      taskADeferred.reject(Object.assign(new Error('store unavailable'), { status: 503 }));
    });
    expect(result.current.graph.task_id).toBe('task-b');
    expect(result.current.error).toBeNull();
  });

  test('clears the graph and records the error when the request fails', async () => {
    const failure = Object.assign(new Error('investigation store is unavailable'), {
      status: 503,
      data: { detail: 'investigation store is unavailable' },
    });
    const fetchGraph = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce(graphResponse());
    const { result } = renderHook(() =>
      useInvestigationGraph({ taskId: 'task-1', fetchGraph }),
    );

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error.status).toBe(503);
    expect(result.current.graph.nodes).toHaveLength(0);

    // retry re-issues the request
    await act(async () => result.current.refresh());
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.graph.nodes).toHaveLength(2);
    expect(fetchGraph).toHaveBeenCalledTimes(2);
  });

  test('forwards maxBaseNodes and reloads when it changes', async () => {
    const fetchGraph = vi.fn().mockResolvedValue(graphResponse());
    const { result, rerender } = renderHook(
      ({ maxBaseNodes }) => useInvestigationGraph({ taskId: 'task-1', maxBaseNodes, fetchGraph }),
      { initialProps: { maxBaseNodes: 200 } },
    );

    await waitFor(() => expect(fetchGraph).toHaveBeenCalledWith('task-1', { maxBaseNodes: 200 }));
    await act(async () => rerender({ maxBaseNodes: 500 }));
    await waitFor(() => expect(fetchGraph).toHaveBeenLastCalledWith('task-1', { maxBaseNodes: 500 }));
    expect(result.current.loading).toBe(false);
  });

  test('does not request without a task and resets state on task change', async () => {
    const fetchGraph = vi.fn();
    const { result, rerender } = renderHook(
      ({ taskId }) => useInvestigationGraph({ taskId, fetchGraph }),
      { initialProps: { taskId: null } },
    );

    expect(fetchGraph).not.toHaveBeenCalled();
    expect(result.current.graph.nodes).toHaveLength(0);

    await act(async () => rerender({ taskId: 'task-1' }));
    await waitFor(() => expect(fetchGraph).toHaveBeenCalledWith('task-1', { maxBaseNodes: 200 }));
  });
});
