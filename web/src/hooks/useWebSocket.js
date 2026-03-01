import { useEffect, useRef, useState, useCallback } from 'react';

/**
 * WebSocket hook with auto-reconnect and message routing.
 * Falls back gracefully when server doesn't support WS.
 *
 * @param {string} url - WebSocket URL (e.g. ws://localhost:8080/ws)
 * @param {Object} handlers - Map of message type → callback
 * @param {Object} options - { enabled, reconnectInterval, maxRetries }
 */
export function useWebSocket(url, handlers = {}, options = {}) {
    const { enabled = true, reconnectInterval = 3000, maxRetries = 5 } = options;
    const [connected, setConnected] = useState(false);
    const [retryCount, setRetryCount] = useState(0);
    const wsRef = useRef(null);
    const handlersRef = useRef(handlers);
    handlersRef.current = handlers;

    const connect = useCallback(() => {
        if (!enabled || !url) return;

        try {
            const ws = new WebSocket(url);
            wsRef.current = ws;

            ws.onopen = () => {
                setConnected(true);
                setRetryCount(0);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    const handler = handlersRef.current[data.type];
                    if (handler) handler(data.payload || data);
                } catch {
                    // Non-JSON message, ignore
                }
            };

            ws.onclose = () => {
                setConnected(false);
                wsRef.current = null;
                setRetryCount((prev) => {
                    if (prev < maxRetries) {
                        const delay = reconnectInterval * Math.pow(2, Math.min(prev, 4));
                        setTimeout(connect, delay);
                        return prev + 1;
                    }
                    return prev;
                });
            };

            ws.onerror = () => {
                ws.close();
            };
        } catch {
            setConnected(false);
        }
    }, [url, enabled, reconnectInterval, maxRetries]);

    useEffect(() => {
        connect();
        return () => {
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [connect]);

    const send = useCallback((data) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data));
        }
    }, []);

    return { connected, send, retryCount };
}

export default useWebSocket;
