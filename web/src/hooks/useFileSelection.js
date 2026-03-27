import { useState, useCallback } from 'react';

/**
 * Custom hook for file selection state and operations
 */
export const useFileSelection = (files = []) => {
  const [selectedFiles, setSelectedFiles] = useState(new Set());
  const [selectAll, setSelectAll] = useState(false);

  const toggleFileSelection = useCallback((filePath) => {
    setSelectedFiles(prev => {
      const newSet = new Set(prev);
      if (newSet.has(filePath)) {
        newSet.delete(filePath);
      } else {
        newSet.add(filePath);
      }
      return newSet;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    if (selectAll) {
      setSelectedFiles(new Set());
      setSelectAll(false);
    } else {
      const allPaths = new Set(files.map(f => f.path));
      setSelectedFiles(allPaths);
      setSelectAll(true);
    }
  }, [selectAll, files]);

  const clearSelection = useCallback(() => {
    setSelectedFiles(new Set());
    setSelectAll(false);
  }, []);

  const getSelectedFilePaths = useCallback(() => {
    return Array.from(selectedFiles);
  }, [selectedFiles]);

  return {
    selectedFiles,
    selectAll,
    selectedCount: selectedFiles.size,
    toggleFileSelection,
    toggleSelectAll,
    clearSelection,
    getSelectedFilePaths
  };
};
