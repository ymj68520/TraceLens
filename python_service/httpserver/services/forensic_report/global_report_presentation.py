"""Deterministic body/appendix presentation of an already validated v8 report."""
import html,re

def markdown_literal(value):
    # Evidence text can contain HTML, image links, or Markdown delimiters.
    # Export it as literal text instead of letting it define report markup.
    return re.sub(r'([\\`*_{}\[\]()#+.!>|~-])',r'\\\1',html.escape(value,quote=False))

def present(manifest,as_html=False):
    if manifest.organization is None:raise ValueError('报告缺少全局组织记录')
    sources={m.evidence_key:m for m in manifest.stage_analysis.materials}
    if as_html:
        def text(value):
            escaped=html.escape(value)
            return re.sub(r'\[\[(c\d+)\]\]',lambda m:f'<a href="#source-{m[1]}">〔来源〕</a>',escaped)
        output=['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
            '<style>body{max-width:960px;margin:40px auto;padding:0 24px;font:16px/1.9 sans-serif}p,pre{white-space:pre-wrap;overflow-wrap:anywhere}section{margin:2em 0}.quality{padding:12px;background:#fff8e8}pre{font-size:13px}a{color:#1648a0}@media print{body{margin:0;max-width:none}section{break-inside:auto}}</style>',
            '<title>'+html.escape(manifest.title)+'</title><body><h1>'+html.escape(manifest.title)+'</h1>',
            '<p class="quality">'+html.escape(manifest.organization.quality_message)+'</p>']
        for index,section in enumerate(manifest.sections,1):
            output.append(f'<section><h2>{index}. {html.escape(section.heading)}</h2>'+''.join('<p>'+text(p)+'</p>' for p in section.content.split('\n\n'))+'</section>')
        for section in manifest.appendices:
            output.append('<aside><h2>'+html.escape(section.heading)+'</h2>'+''.join('<p>'+text(p)+'</p>' for p in section.content.split('\n\n'))+'</aside>')
        output.append('<h2>附录：冻结来源与引文位置</h2>')
        for citation in manifest.citations:
            source=sources.get(citation.evidence_key)
            if source is None:continue
            output.append(f'<section id="source-{html.escape(citation.citation_id,quote=True)}"><h3>'+html.escape(citation.evidence_key)+'</h3>')
            output.append('<p>来源摘要（文件或派生记录）：'+html.escape(source.source_sha256 or '不可用')+'<br>冻结文本摘要：'+source.content_sha256+'</p>')
            for span in manifest.organization.spans:
                if span.material_id==source.material_id:
                    output.append(f'<blockquote>字符 {span.character_start}—{span.character_end}：'+html.escape(span.quote)+'</blockquote>')
            output.append('<pre>'+html.escape(source.text or '本轮无可用正文')+'</pre></section>')
        output.append('</body></html>');return ''.join(output)
    output=['# '+markdown_literal(manifest.title),'',markdown_literal(manifest.organization.quality_message),'']
    def md(value):
        return ''.join(f'[来源](#source-{part[2:-2]})' if re.fullmatch(r'\[\[c\d+\]\]',part) else markdown_literal(part)
                       for part in re.split(r'(\[\[c\d+\]\])',value))
    for index,section in enumerate(manifest.sections,1):output.extend([f'## {index}. {markdown_literal(section.heading)}','',md(section.content),''])
    for section in manifest.appendices:output.extend(['## '+markdown_literal(section.heading),'',md(section.content),''])
    output.extend(['## 附录：冻结来源与引文位置',''])
    for citation in manifest.citations:
        source=sources.get(citation.evidence_key)
        if source is None:continue
        output.extend([f'<a id="source-{html.escape(citation.citation_id,quote=True)}"></a>','',markdown_literal(citation.evidence_key),'',
                       '来源摘要（文件或派生记录）：'+(source.source_sha256 or '不可用'),'', '冻结文本摘要：'+source.content_sha256,''])
        for span in manifest.organization.spans:
            if span.material_id==source.material_id:output.extend([f'字符 {span.character_start}—{span.character_end}：','',*('> '+markdown_literal(line) for line in span.quote.splitlines()),''])
    return '\n'.join(output)
