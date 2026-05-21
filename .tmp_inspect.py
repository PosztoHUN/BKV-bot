from pathlib import Path
text = Path('main.py').read_text(encoding='utf-8')
search = 'f"Környező megálló: {i[\'stop\']}\n"\n            f"Forgalmi:'
print('pattern:', repr(search))
print('count:', text.count(search))
idx = text.find(search)
print('idx:', idx)
if idx != -1:
    print(repr(text[idx-80:idx+80]))
