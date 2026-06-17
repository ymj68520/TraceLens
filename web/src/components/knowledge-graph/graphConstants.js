// graphConstants.js
// Shared constants for the Knowledge Graph page and its subcomponents.

// Node color palette by entity label.
export const NODE_COLORS = {
    Entity: '#6366f1',
    File: '#06b6d4',
    Process: '#f59e0b',
    User: '#10b981',
    Network: '#ec4899',
    Registry: '#8b5cf6',
    Event: '#ef4444',
    Directory: '#14b8a6',
    default: '#94a3b8',
};

// Resolve a node color by its label (falls back to slate).
export const getNodeColor = (label) => NODE_COLORS[label] || NODE_COLORS.default;
