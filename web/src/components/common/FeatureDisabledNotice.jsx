import { Link } from 'react-router-dom';
import { ShieldOff } from 'lucide-react';
import { useTranslation } from '../../hooks/useTranslation';

/**
 * Placeholder rendered when a module is disabled by the backend feature
 * switches (mvp-phase1-acceptance SPEC §2/§4). The route stays registered so
 * the overall page surface is unchanged; the module body is not mounted.
 */
const FeatureDisabledNotice = ({ title, backTo = '/dashboard' }) => {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-slate-500 dark:text-slate-400" data-testid="feature-disabled">
      <ShieldOff size={48} className="text-slate-300 dark:text-slate-600" />
      <p className="text-lg font-medium">{title || t('feature.disabled', '该功能在当前验收版本中未启用')}</p>
      <Link
        to={backTo}
        className="px-4 py-2 rounded-xl text-sm font-medium text-white bg-slate-700 hover:bg-slate-600 transition-colors"
      >
        {t('common.back', '返回首页')}
      </Link>
    </div>
  );
};

export default FeatureDisabledNotice;
