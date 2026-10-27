"""Read-side quality results, separate from execution and frozen report bytes."""
from pydantic import BaseModel, Field


class ReportQuality(BaseModel):
    status: str
    label: str
    reasons: tuple[str, ...] = ()
    counts: dict[str, int | None] = Field(default_factory=dict)
    scope: str = '当前报告冻结版本；不代表整盘材料'
    rule_version: str = 'delivery-quality:v1'


def report_quality(manifest=None, *, execution_status=None, error_code=None):
    if execution_status == 'failed':
        return ReportQuality(status='failed', label='校验或执行未通过', reasons=(
            '本次生成没有可交付的新报告；请查看失败原因并重新核对来源。',))
    if manifest is None:
        return ReportQuality(status='pending', label='待校验', reasons=('执行结束前不判定交付质量。',))
    organization = manifest.organization
    if organization is None:
        return ReportQuality(status='unassessed', label='历史版本未评估', reasons=(
            '该版本没有当前质量账本，不能从执行完成推断内容已通过质量检查。',))
    coverage = organization.coverage
    counts = {state: sum(row.get('status') == state for row in coverage)
              for state in ('extracted', 'partial', 'deferred', 'unavailable')}
    counts['sources'] = len(coverage)
    counts['findings'] = len(organization.findings)
    counts['body_findings'] = sum(v == '正文解释' for v in organization.plan.finding_disposition.values())
    reasons = list(organization.warnings)
    for key, label in (('partial', '部分完成'), ('deferred', '暂缓'), ('unavailable', '不可用')):
        if counts[key]: reasons.append(f'{counts[key]} 份材料{label}，不能据此认定没有相关活动。')
    limited = organization.quality == 'preliminary' or bool(reasons)
    return ReportQuality(status='limited' if limited else 'passed',
        label='有范围限制' if limited else '来源与结构校验通过',
        reasons=tuple(dict.fromkeys([*reasons, '机器校验不代替对关键结论的人工复核。'])), counts=counts)
