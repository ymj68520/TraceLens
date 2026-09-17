import { useEffect, useState } from 'react';
import { FEATURE_DEFAULTS, fetchFeatures } from '../services/featuresService';

/**
 * React hook over the backend feature switches. Renders the MVP (disabled)
 * defaults until the fetch resolves, keeping the trimmed UI stable on slow
 * or failing backends.
 */
export const useFeatures = () => {
  const [features, setFeatures] = useState(FEATURE_DEFAULTS);

  useEffect(() => {
    let alive = true;
    fetchFeatures().then((next) => {
      if (alive) setFeatures(next);
    });
    return () => {
      alive = false;
    };
  }, []);

  return features;
};

export default useFeatures;
