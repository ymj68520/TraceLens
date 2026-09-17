import { useFeatures } from '../../hooks/useFeatures';
import FeatureDisabledNotice from './FeatureDisabledNotice';

/**
 * Route-level feature gate (mvp-phase1-acceptance SPEC §2/§4). Keeps the
 * route registered (page surface unchanged) while swapping the module body
 * for a notice when the backend flag is off.
 */
const FeatureGate = ({ flag, children }) => {
  const features = useFeatures();
  if (!features[flag]) {
    return <FeatureDisabledNotice />;
  }
  return children;
};

export default FeatureGate;
