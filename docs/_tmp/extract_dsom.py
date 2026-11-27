import sys, zipfile, re
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

src = r"C:\Users\Administrator\Documents\xwechat_files\wxid_ch66sa07stso22_8aeb\msg\file\2026-10\DSOM_v5.0自演化系统终极治理方案_最终封卷版(1).docx"
out = r"D:\拾光剪影\docs\_tmp\DSOM_v5.0_text.md"

doc = Document(src)
body = doc.element.body
lines = []
for child in body.iterchildren():
    tag = child.tag.split('}')[-1]
    if tag == 'p':
        p = Paragraph(child, doc)
        t = p.text.rstrip()
        style = (p.style.name or '')
        if t:
            if style.lower().startswith('heading') or style.startswith('标题'):
                lvl = ''.join(ch for ch in style if ch.isdigit())
                n = int(lvl) if lvl else 1
                lines.append('#' * min(max(n, 1), 6) + ' ' + t)
            else:
                lines.append(t)
        else:
            lines.append('')
    elif tag == 'tbl':
        tbl = Table(child, doc)
        lines.append('')
        for row in tbl.rows:
            cells = [c.text.replace('\n', ' ').strip() for c in row.cells]
            lines.append('| ' + ' | '.join(cells) + ' |')
        lines.append('')

text = '\n'.join(lines)
text = re.sub(r'\n{3,}', '\n\n', text)
with open(out, 'w', encoding='utf-8') as f:
    f.write(text)
print('chars:', len(text))
print('paragraphs:', len(doc.paragraphs), 'tables:', len(doc.tables))