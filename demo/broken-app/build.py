import json
from pathlib import Path
from calculator import add

assert add(2, 3) == 5, 'Cannot build a broken calculator'
Path('dist').mkdir(exist_ok=True)
Path('dist/result.json').write_text(json.dumps({'result': add(2, 3), 'verified': True}))
print('Built dist/result.json')
