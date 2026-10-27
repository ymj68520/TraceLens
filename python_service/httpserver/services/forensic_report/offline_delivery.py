"""Version-scoped, script-free offline delivery from the strict frozen manifest."""
from __future__ import annotations
import hashlib
import html
import io
import json
import os
import re
import zipfile
from pathlib import Path
from .ids import safe_segment
from .report_quality import report_quality
from .global_report_presentation import markdown_literal

RENDERER = 'offline-report:v1'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def projection(manifest, version):
    raw = manifest.model_dump(mode='json')
    materials = manifest.stage_analysis.materials if manifest.stage_analysis else ()
    organization = manifest.organization
    source_by_key = {m.evidence_key: m for m in materials}
    sources = []
    for number, citation in enumerate(manifest.citations, 1):
        source = source_by_key.get(citation.evidence_key)
        spans = [s.model_dump(mode='json') for s in organization.spans if source and s.material_id == source.material_id] if organization else []
        if source and not organization and manifest.stage_analysis:
            for direction in manifest.stage_analysis.directions:
                spans.extend(s.model_dump(mode='json') for s in (*direction.supporting_refs, *direction.counter_refs) if s.material_id == source.material_id)
        sources.append({'number': number, 'citation_id': citation.citation_id, 'evidence_key': citation.evidence_key,
            'material_id': source.material_id if source else None,
            'source_sha256': source.source_sha256 if source else None,
            'content_sha256': source.content_sha256 if source else None,
            'text': source.text if source else '', 'spans': spans,
            'limitations': list(source.limitations) if source else ['旧版未冻结来源正文及哈希，离线包不补造来源。'],
            'provenance': {k: v for k, v in (source.source_provenance or {}).items() if k in (
                'parser_version', 'projection_version', 'result_set_id', 'source_table', 'source_id', 'record_id', 'record_hash')} if source else {}})
    return {'renderer_version': RENDERER, 'report_id': manifest.report_id, 'task_id': manifest.task_id,
        'version': version, 'generated_at': manifest.generated_at, 'title': manifest.title,
        'original_manifest_sha256': sha(encoded(raw)), 'manifest_hash_basis':'canonical_json_utf8', 'input_hash': manifest.input_hash,
        'quality': report_quality(manifest).model_dump(),
        'sections': [s.model_dump(mode='json') for s in manifest.sections],
        'appendices': [s.model_dump(mode='json') for s in manifest.appendices],
        'sources': sources,
        'findings': [f.model_dump(mode='json') for f in organization.findings] if organization else [],
        'paragraphs': [p.model_dump(mode='json') for p in organization.paragraphs] if organization else [],
        'chapter_names': {c.section_id:c.heading for c in organization.plan.chapters} if organization else {},
        'coverage': list(organization.coverage) if organization else [],
        'omissions': ['仅包含当前版本冻结的文字和引用；未复制完整检材、图像字节、服务提示词或本机提取目录。',
                      '来源哈希可能对应派生记录，冻结文本哈希对应本包中的文本；二者不等于原镜像整盘哈希。']}


def render(view, as_html=True):
    numbers = {s['citation_id']: s['number'] for s in view['sources']}
    def prose(value):
        parts = re.split(r'(\[\[[^\]]+\]\])', value)
        out = []
        for part in parts:
            cid = part[2:-2] if part.startswith('[[') and part.endswith(']]') else None
            number = numbers.get(cid)
            if number:
                out.append(f'<a href="#source-{number}">〔{number}〕</a>' if as_html else f'[〔{number}〕](#source-{number})')
            else: out.append(html.escape(part) if as_html else markdown_literal(part))
        return ''.join(out)
    def para(value):
        return '<p>'+prose(value)+'</p>' if as_html else prose(value)+'\n'
    def heading(value, level=2):
        return f'<h{level}>'+html.escape(value)+f'</h{level}>' if as_html else '#'*level+' '+markdown_literal(value)+'\n'
    out = []
    if as_html:
        out += ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(view['title'])+'</title>',
            '<style>body{max-width:980px;margin:32px auto;padding:0 24px;font:16px/1.8 sans-serif;color:#172033}p,pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}pre{font:13px/1.7 monospace;background:#f4f6fa;padding:16px}a{color:#175ca5}section{margin:32px 0}dt{font-weight:bold}blockquote{border-left:3px solid #a9bed6;padding-left:16px}summary{cursor:pointer}@media print{body{max-width:none;margin:0;font-size:11pt}a{color:inherit;text-decoration:none}pre{background:none}h2,h3{break-after:avoid}}</style></head><body>']
    out += [heading(view['title'], 1), para(f"版本 {view['version']} · 报告编号 {view['report_id']} · 生成时间 {view['generated_at']}"),
        para('交付质量：'+view['quality']['label']), para('原报告规范清单 SHA-256：'+view['original_manifest_sha256'])]
    counts=view['quality'].get('counts', {})
    if counts:
        out.append(para(f"冻结来源 {counts.get('sources', '未记录')} 份；本轮提取完成 {counts.get('extracted', '未记录')}，部分完成 {counts.get('partial', '未记录')}，暂缓 {counts.get('deferred', '未记录')}，不可用 {counts.get('unavailable', '未记录')}。"))
    if view['quality']['reasons']:
        out.append('<p><a href="#quality-details">查看全部质量说明与未完成范围</a></p>' if as_html else '[查看全部质量说明与未完成范围](#quality-details)\n')
    out.extend(para(r) for r in view['omissions'])
    for index, section in enumerate(view['sections']+view['appendices'], 1):
        out.append(heading(f"{index}. {section['heading']}"))
        out.extend(para(p) for p in section['content'].split('\n\n'))
        # Older reports only have section-level citations: do not guess a sentence.
        if not re.search(r'\[\[', section['content']) and section.get('citation_ids'):
            out.append(para('本章引用（未推测逐句位置）：'+''.join('[['+c+']]' for c in section['citation_ids'])))
    out.append('<div id="quality-details"></div>' if as_html else '<a id="quality-details"></a>\n')
    out.append(heading('附录：质量说明与未完成范围'))
    out.extend(para(r) for r in view['quality']['reasons'])
    out.append(heading('附录：主张、段落与来源映射'))
    finding_numbers = {f['finding_id']:i for i,f in enumerate(view['findings'],1)}
    for binding in view['paragraphs']:
        title = view['chapter_names'].get(binding['section_id'], binding['section_id'])
        out.append(para(f"{title} · 段落 {binding['paragraph_index']+1}：使用发现 "+'、'.join(str(finding_numbers.get(fid,'未记录')) for fid in binding['finding_ids'])+'；来源 '+''.join('[['+cid+']]' for cid in binding['citation_ids'])))
    for index, finding in enumerate(view['findings'], 1):
        kind = {'observation':'材料观察','inference':'模型推断','hypothesis':'待核假设'}.get(finding['kind'], '待核对')
        out.extend([heading(f'发现 {index} · {kind}', 3), para(finding['statement'])])
        out.extend(para('限制：'+value) for value in finding.get('limitations', []))
        out.extend(para('其他解释：'+value) for value in finding.get('alternatives', []))
        related = [s for s in view['sources'] if any(p.get('span_id') in (*finding.get('supporting_spans', []), *finding.get('counter_spans', [])) for p in s['spans'])]
        out.append(para('关联来源：'+''.join('[['+s['citation_id']+']]' for s in related)))
        if finding.get('counter_spans'):out.append(para('该发现包含反向或限制片段，请结合来源片段和正文限制一并阅读。'))
    out.append(heading('附录：材料覆盖'))
    source_numbers = {s['material_id']: s['citation_id'] for s in view['sources']}
    for row in view['coverage']:
        cid = source_numbers.get(row['material_id'])
        label = {'extracted':'已完成本轮提取','partial':'部分完成','deferred':'暂缓','unavailable':'不可用'}.get(row.get('status'),'待核对')
        out.append(para(f"{label}：{row.get('reason','')}；{row.get('exclusion_reason','')}"+('[['+cid+']]' if cid else '')))
    out.append(heading('附录：引用清单、来源摘要与原文位置'))
    for source in view['sources']:
        number = source['number']
        out.append(f'<section id="source-{number}">' if as_html else f'<a id="source-{number}"></a>\n')
        out.extend([heading(f"〔{number}〕{source['citation_id']}", 3), para(source['evidence_key']),
            para('来源 SHA-256：'+(source['source_sha256'] or '未记录')),
            para('冻结文本 SHA-256：'+(source['content_sha256'] or '未记录'))])
        out.extend(para(note) for note in source['limitations'])
        for span in source['spans']:
            out += [para(f"字符位置 [{span['character_start']}, {span['character_end']})，按 Unicode 字符计数："),
                '<blockquote>'+html.escape(span['quote'])+'</blockquote>' if as_html else '> '+markdown_literal(span['quote']).replace('\n','\n> ')+'\n']
        out.append('<pre>'+html.escape(source['text'] or '本版本没有可用原文')+'</pre>' if as_html else '\n'.join('> '+markdown_literal(line) for line in (source['text'] or '本版本没有可用原文').splitlines()))
        if as_html: out.append('</section>')
    if as_html: out.append('</body></html>')
    return '\n'.join(out)


def offline_files(manifest, version):
    view = projection(manifest, version)
    files = {'report.html': render(view).encode(), 'report.md': render(view, False).encode(),
             'sources.json': encoded(view['sources']),
             'claims.json': encoded({'findings':view['findings'],'paragraphs':view['paragraphs'],'coverage':view['coverage']})}
    index = {k:v for k,v in view.items() if k not in ('sections','appendices','sources','findings','paragraphs','coverage')}
    index['projection_sha256'] = sha(encoded(view))
    index['export_id'] = 'delivery_'+index['projection_sha256'][:24]
    index['export_mode'] = 'frozen_text_projection'
    index['redaction_applied'] = False
    index['files'] = {name: {'sha256':sha(data),'bytes':len(data)} for name,data in files.items()}
    files['manifest.json'] = encoded(index)
    return files


def offline_archive(manifest, version, root):
    files = offline_files(manifest, version)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026,1,1,0,0,0));info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    content = buffer.getvalue();checksum = sha(content)
    directory = Path(root).absolute()/'exports'/safe_segment(manifest.task_id)/safe_segment(manifest.report_id)
    if not directory.resolve().is_relative_to(Path(root).resolve()): raise ValueError('离线导出路径越界')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/(checksum+'.zip')
    try:
        with path.open('xb') as stream: stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content: raise ValueError('既有离线包摘要不符，禁止覆盖')
    return content, checksum
