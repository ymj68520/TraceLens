/**
 * SmsThreads — renders the 短信息 chapter as a conversation bubble list,
 * grouped by the remote address. Mirrors the reference report's messaging view.
 */
import { SectionCard, EmptySection, val, fmtTime, smsTypeLabel, Badge } from './shared';

export default function SmsThreads({ pageData }) {
  const records = pageData?.records || [];
  const total = pageData?.total ?? records.length;

  return (
    <SectionCard title="短信息" total={total}>
      {records.length === 0 ? (
        <EmptySection />
      ) : (
        <ul className="space-y-1.5">
          {records.map((r, i) => {
            const outgoing = Number(r.type) === 2 || Number(r.type) === 4;
            return (
              <li key={i} className="flex gap-2">
                <div className="mt-0.5 h-7 w-7 shrink-0 rounded-full bg-slate-200 dark:bg-slate-700" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-slate-500 dark:text-slate-400">
                    <span className="font-medium text-slate-700 dark:text-slate-200">{val(r.address)}</span>
                    {r.person && <span>{r.person}</span>}
                    <span>{fmtTime(r.date)}</span>
                    <Badge className="bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                      {smsTypeLabel(r.type)}
                    </Badge>
                  </div>
                  <div
                    className={`mt-0.5 inline-block max-w-full rounded-lg px-3 py-1.5 text-sm break-words ${
                      outgoing
                        ? 'bg-primary-50 text-slate-800 dark:bg-primary-900/30 dark:text-slate-100'
                        : 'bg-slate-100 text-slate-800 dark:bg-slate-700/60 dark:text-slate-100'
                    }`}
                  >
                    {val(r.body)}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </SectionCard>
  );
}
