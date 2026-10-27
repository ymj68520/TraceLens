"""Read-side ingestion completeness; COMPLETED only describes the worker."""
import json

def ingestion_quality(job):
    result = job.get('result') or {}
    if isinstance(result, str):
        try: result = json.loads(result)
        except ValueError: result = {}
    if not isinstance(result, dict): result = {}
    def count(*keys):
        for key in keys:
            value = result.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0: return value
        return None
    total = count('episodes_total', 'total')
    successful = count('episodes_successful', 'successful')
    failed = count('episodes_failed', 'failed')
    state = str(job.get('status', '')).lower()
    active = state in ('pending', 'running')
    reasons = []
    if failed: reasons.append(f'{failed} 条摄取未成功，执行完成不表示全部材料已经进入图谱。')
    if job.get('error') or result.get('error'): reasons.append('本轮记录了摄取错误，需核对诊断并重试。')
    if total is None or successful is None or failed is None: reasons.append('历史运行没有完整成功/失败计数，不按零失败展示。')
    if total is not None and successful is not None and successful > total: reasons.append('摄取计数不一致，需复核运行记录。')
    if all(v is not None for v in (total, successful, failed)) and successful+failed>total: reasons.append('成功与失败计数超过本轮总数，需复核运行记录。')
    if state not in ('pending','running','completed','failed','cancelled'): reasons.append('运行状态未知，不能判为质量通过。')
    if total == 0: reasons.append('本轮没有可摄取记录，不代表来源不存在相关活动。')
    pending = max(0, total-successful-failed) if all(v is not None for v in (total,successful,failed)) else None
    if pending: reasons.append(f'{pending} 条尚未完成摄取。')
    all_failed = bool(total and successful == 0 and failed is not None and failed >= total)
    quality = 'pending' if active else 'failed' if state == 'failed' or all_failed else 'limited' if reasons or state == 'cancelled' else 'passed'
    return {'status':quality,'label':{'pending':'处理中','failed':'摄取失败','limited':'有范围限制','passed':'本轮摄取计数通过'}[quality],
        'total':total,'successful':successful,'failed':failed,'unprocessed':pending,
        'reasons':reasons,'retryable':not active and bool(failed or pending or job.get('error') or result.get('error')),
        'scope':'此运行的计数；不累加历史运行，也不代表整盘图谱完整'}
