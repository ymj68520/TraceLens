import { useState, useEffect, useCallback } from 'react';
import { getLargestFiles, getExtensionAnalysis } from '../services/forensicsService';

/**
 * Custom hook for fetching files data
 */
export const useFilesData = (taskId) => {
  const [largestFiles, setLargestFiles] = useState([]);
  const [extensionAnalysis, setExtensionAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchLargestFiles = useCallback(async (limit = 100) => {
    if (!taskId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const data = await getLargestFiles(taskId, limit);
      setLargestFiles(data.files || []);
    } catch (err) {
      setError(err.message);
      console.error('Failed to fetch largest files:', err);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  const fetchExtensionAnalysis = useCallback(async () => {
    if (!taskId) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const data = await getExtensionAnalysis(taskId);
      setExtensionAnalysis(data);
    } catch (err) {
      setError(err.message);
      console.error('Failed to fetch extension analysis:', err);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    if (taskId) {
      fetchLargestFiles();
      fetchExtensionAnalysis();
    }
  }, [taskId, fetchLargestFiles, fetchExtensionAnalysis]);
  return {
    largestFiles,
    extensionAnalysis,
    loading,
    error,
    fetchLargestFiles,
    fetchExtensionAnalysis,
    setLargestFiles
  };
};
