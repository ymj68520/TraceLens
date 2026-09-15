import { SkeletonBlock } from '../ui/PageScaffold';

/** Grid-item skeleton matching the CaseCard layout, for list loading state. */
export function CaseCardSkeleton({ count = 6 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="card card-pad space-y-3" aria-hidden>
          <div className="flex items-center gap-2.5">
            <SkeletonBlock className="h-8 w-8 rounded-md" />
            <div className="flex-1 space-y-1.5">
              <SkeletonBlock className="h-3.5 w-2/3" />
              <SkeletonBlock className="h-2.5 w-1/3" />
            </div>
          </div>
          <SkeletonBlock className="h-2.5 w-full" />
          <SkeletonBlock className="h-1.5 w-full rounded-full" />
          <SkeletonBlock className="h-2.5 w-4/5" />
          <div className="flex gap-2 pt-1">
            <SkeletonBlock className="h-7 w-20" />
            <SkeletonBlock className="h-7 w-20" />
          </div>
          <SkeletonBlock className="h-2.5 w-1/2" />
        </div>
      ))}
    </>
  );
}

export default CaseCardSkeleton;
