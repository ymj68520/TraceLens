import { useState, useCallback } from 'react';
import { startExtraction, pollExtractionStatus } from '../services/extractionService';

/**
 * Custom hook for file extraction operations
 */
export const useFileExtraction = (taskId) => {
  const [extractionMode, setExtractionMode] = useState('all');
  const [extractionPattern, setExtractionPattern] = useState('');
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [extractionStatus, setExtractionStatus] = useState('idle');
  const [extractionProgress, setExtractionProgress] = useState(0);
  const [extractionMessage, setExtractionMessage] = useState('');
  const [extractionJobId, setExtractionJobId] = useState(null);

  const handleExtractFiles = useCallback(async () => {
    if (!taskId) return;

    setExtractionStatus('running');
    setExtractionProgress(0);
    setExtractionMessage('Starting extraction...');

    try {
      const jobData = await startExtraction({
        task_id: taskId,
        mode: extractionMode,
        pattern: extractionPattern,
        include_deleted: includeDeleted,
        overwrite: overwrite
      });

      const jobId = jobData.job_id;
      setExtractionJobId(jobId);
      setExtractionMessage(`Job started: ${jobId}`);

      const finalStatus = await pollExtractionStatus(jobId, (status) => {
        setExtractionProgress(status.progress || 0);
        setExtractionMessage(status.message || 'Extracting...');
      });

      if (finalStatus.status === 'completed') {
        setExtractionStatus('completed');
        setExtractionMessage(`✅ Extracted ${finalStatus.extracted_files} files to ${finalStatus.output_path}`);
      } else if (finalStatus.status === 'failed') {
        setExtractionStatus('failed');
        setExtractionMessage(`❌ Extraction failed: ${finalStatus.error_details}`);
      }
    } catch (err) {
      setExtractionStatus('failed');
      setExtractionMessage(`❌ Error: ${err.message}`);
      console.error('Extraction error:', err);
    }
  }, [taskId, extractionMode, extractionPattern, includeDeleted, overwrite]);

  const resetExtraction = useCallback(() => {
    setExtractionStatus('idle');
    setExtractionProgress(0);
    setExtractionMessage('');
    setExtractionJobId(null);
  }, []);

  return {
    extractionMode,
    setExtractionMode,
    extractionPattern,
    setExtractionPattern,
    includeDeleted,
    setIncludeDeleted,
    overwrite,
    setOverwrite,
    extractionStatus,
    extractionProgress,
    extractionMessage,
    extractionJobId,
    handleExtractFiles,
    resetExtraction
  };
};
