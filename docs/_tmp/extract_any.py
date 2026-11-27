import sys, re
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

src, out = sys.argv[1], sys.argv[2]
doc = Document(src)
lines = []
for child in doc.element.body.iterchildren():
    tag = child.tag.split('}')[-1]
    if tag == 'p':
        p = Paragraph(child, doc)
        t = p.text.rstrip()
        style = (p.style.name or '')
        if t:
            if style.lower().startswith('heading') or style.startswith('标题'):
                lvl = ''.join(ch for ch in style if ch.isdigit())
                lines.append('#' * min(max(int(lvl) if lvl else 1, 1), 6) + ' ' + t)
            else:
                lines.append(t)
        else:
            lines.append('')
    elif tag == 'tbl':
        tbl = Table(child, doc)
        lines.append('')
        for row in tbl.rows:
            lines.append('| ' + ' | '.join(c.text.replace('\n', ' ').strip() for c in row.cells) + ' |')
        lines.append('')
text = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines))
open(out, 'w', encoding='utf-8').write(text)
print('chars', len(text), 'paras', len(doc.paragraphs), 'tables', len(doc.tables))
