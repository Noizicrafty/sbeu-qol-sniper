"""Build a local, self-contained-in-directory review report from measured results."""
import html
import json
from pathlib import Path


def main():
    directory=Path('data/frame-validation');out=directory/'all-seven'
    rows=json.loads((out/'results.json').read_text(encoding='utf8'))
    replay=json.loads((directory/'realtime-reveal-benchmark.json').read_text(encoding='utf8'))
    assert len(rows)==14,'Wait for both regions of all seven screenshots'
    expected=sum(r['refined']['expected'] for r in rows);matched=sum(r['refined']['matched'] for r in rows)
    ambiguous=sum(r['refined']['ambiguous'] for r in rows)
    extra=sum(len(r['refined']['extra']) for r in rows)
    wrong=sum(len(r['refined']['wrong']) for r in rows)
    def esc(value):return html.escape(str(value))
    body=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>ItemSniper — проверка семи скриншотов</title>
    <style>body{{font:16px/1.6 Segoe UI,sans-serif;background:#101512;color:#e5e9df;max-width:1200px;margin:auto;padding:32px}}h1,h2{{color:#addc72}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #384238;padding:10px}}img{{width:100%;height:auto}}a{{color:#addc72}}small{{color:#b7bdb5}}.note{{padding:20px;background:#253021;border-radius:8px}}</style>
    <h1>Проверка семи скриншотов</h1><p>12.11.2026 · локальные OCR RU/EN · полный индекс 5 636 ID · только пиксели.</p>
    <p class="note">Совпало семейство и положение: <strong>{matched} / {expected}</strong> видимых вхождений ({matched/expected:.1%}).
    Среди совпадений {ambiguous} имеют неопределённый точный вариант. Это проверка семейств, а не точности идентификации всех ID игры.
    Ошибочных названий в сопоставленных слотах: {wrong}; несопоставленных рамок: {extra}.</p>
    <p>193 вхождения размечены вручную на двух областях каждого кадра. Одни предметы повторяются между кадрами.
    Панель быстрого доступа и обрезанные предметы исключены. Правильное положение требует IoU ≥ 0,5.
    FIR и числа стопок не имеют отдельной ручной разметки и не включены в показатель точности.</p>
    <h2>Результаты по кадрам</h2><table><tr><th>Кадр</th><th>Персонаж</th><th>Добыча</th><th>Повороты</th></tr>'''
    for stamp in dict.fromkeys(r['stamp'] for r in rows):
        parts=[r for r in rows if r['stamp']==stamp]
        values={r['kind']:f"{r['refined']['matched']} / {r['refined']['expected']}" for r in parts}
        rotated=sum(r['refined']['rotated_matched'] for r in parts);total=sum(r['refined']['rotated_expected'] for r in parts)
        body+=f'<tr><td><a href="#{stamp}">{stamp}</a></td><td>{values["inventory"]}</td><td>{values["loot"]}</td><td>{rotated} / {total}</td></tr>'
    body+='</table><h2>Задержка при раскрытии</h2><p>Воспроизведение перехода со штриховкой поверх реального слота. Работают быстрый проход и фоновые задачи; проверка результата каждые 50 мс. Время захвата живой игры и отрисовки Windows в замер не входит.</p><table><tr><th>Предмет</th><th>После раскрытия</th><th>Стабильный кадр</th><th>Скрытая клетка</th></tr>'
    for case in replay:
        body+=f'<tr><td>{esc(case["item"])}</td><td>{case["reveal_ms"]} мс · {"найден" if case["detected"] else "пропуск"}</td><td>{case["unchanged_ms"]} мс</td><td>{len(case["hidden_false_hits"])} ложных находок</td></tr>'
    body+='</table><p>Все пять переходов проверяются без F7/F10. Модели предварительно прогреты. При первом открытии плотной сетки полный разбор занимает несколько секунд; эти замеры не означают одинаковую задержку для каждого предмета.</p><h2>Пропуски и локализация</h2>'
    for row in rows:
        value=row['refined']
        if not value['missed'] and not value['wrong'] and not value['extra']:continue
        body+=f'<h3>{row["stamp"]} · {esc(row["kind"])}</h3><ul>'
        for obj in value['missed']:body+=f'<li>Пропуск: {esc(obj["name"])} · {esc(obj["box"])}</li>'
        for obj in value['wrong']:body+=f'<li>Ошибочное имя: {esc(obj["expected"]["name"])} → {esc(obj["hit"]["name"])}</li>'
        for obj in value['extra']:body+=f'<li>Несопоставленная рамка: {esc(obj["name"])} · {esc(obj["box"])}</li>'
        body+='</ul>'
    body+='<h2>Все исходные кадры с разметкой</h2><p>Зелёный — семейство и рамка совпали. Красный — не прошёл проверку. Жёлтая подпись — результат распознавания. Отдельные пресеты остаются неопределёнными.</p>'
    for stamp in dict.fromkeys(r['stamp'] for r in rows):
        body+=f'<h3 id="{stamp}">{stamp}</h3><a href="{stamp}.jpg"><img loading="lazy" src="{stamp}.jpg" alt="Проверка кадра {stamp}"></a>'
    body+='<p><a href="results.json">Полные результаты, координаты и SHA-256 исходных кадров</a> · <a href="../realtime-reveal-benchmark.json">Замеры раскрытия</a></p></html>'
    (out/'report.html').write_text(body,encoding='utf8')
    print({'matched':matched,'expected':expected,'ambiguous':ambiguous,'extra':extra,'wrong':wrong})


if __name__=='__main__':main()
