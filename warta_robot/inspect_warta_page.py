import json
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright


WARTA_URL = "https://eagent.warta.pl"
OUTPUT_DIR = Path("page_inspections")


JS_INSPECT = """
() => {
    function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return (
            style &&
            style.visibility !== 'hidden' &&
            style.display !== 'none' &&
            rect.width > 0 &&
            rect.height > 0
        );
    }

    function textOf(el) {
        if (!el) return '';
        return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    }

    function attr(el, name) {
        return el.getAttribute(name) || '';
    }

    function getNearbyText(el) {
        const result = [];

        try {
            if (el.id) {
                const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (label) result.push(textOf(label));
            }
        } catch (e) {}

        const parent = el.closest('div, label, form, section, fieldset, tr, td');
        if (parent) {
            const parentText = textOf(parent);
            if (parentText && parentText.length < 700) {
                result.push(parentText);
            }
        }

        let previous = el.previousElementSibling;
        let steps = 0;

        while (previous && steps < 3) {
            const txt = textOf(previous);
            if (txt) result.push(txt);
            previous = previous.previousElementSibling;
            steps++;
        }

        return [...new Set(result)].filter(Boolean).join(' | ');
    }

    function cssPath(el) {
        if (el.id) return `#${CSS.escape(el.id)}`;

        const parts = [];
        let node = el;

        while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
            let part = node.nodeName.toLowerCase();

            if (node.className && typeof node.className === 'string') {
                const classes = node.className
                    .split(/\\s+/)
                    .filter(Boolean)
                    .slice(0, 2)
                    .map(c => '.' + CSS.escape(c))
                    .join('');
                part += classes;
            }

            const parent = node.parentElement;

            if (parent) {
                const sameTag = Array.from(parent.children)
                    .filter(child => child.nodeName === node.nodeName);

                if (sameTag.length > 1) {
                    part += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
                }
            }

            parts.unshift(part);
            node = parent;
        }

        return parts.join(' > ');
    }

    const elements = Array.from(
        document.querySelectorAll('input, select, textarea, button, a, [role="button"], [ng-click]')
    ).filter(visible);

    return elements.map((el, index) => {
        const rect = el.getBoundingClientRect();

        return {
            index,
            tag: el.tagName.toLowerCase(),
            type: attr(el, 'type'),
            text: textOf(el),
            value: el.value || '',
            placeholder: attr(el, 'placeholder'),
            name: attr(el, 'name'),
            id: attr(el, 'id'),
            aria_label: attr(el, 'aria-label'),
            role: attr(el, 'role'),
            ng_model: attr(el, 'ng-model'),
            ng_click: attr(el, 'ng-click'),
            ng_if: attr(el, 'ng-if'),
            ng_show: attr(el, 'ng-show'),
            ng_hide: attr(el, 'ng-hide'),
            class: attr(el, 'class'),
            href: attr(el, 'href'),
            nearby_text: getNearbyText(el),
            css_path: cssPath(el),
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height)
        };
    });
}
"""


def inspect_page_with_retry(page, attempts=5):
    """
    Warta может перерисовывать Angular-страницу.
    Поэтому делаем несколько попыток.
    """
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass

            # Небольшая пауза, чтобы Angular успел дорисовать страницу.
            page.wait_for_timeout(1000)

            return page.evaluate(JS_INSPECT)

        except Exception as error:
            last_error = error
            print(f"Попытка сканирования {attempt}/{attempts} не удалась: {error}")
            time.sleep(1)

    raise RuntimeError(f"Не удалось просканировать страницу после {attempts} попыток: {last_error}")


def save_inspection(page, name):
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    base = OUTPUT_DIR / f"{timestamp}_{safe_name}"

    elements = inspect_page_with_retry(page)

    data = {
        "url": page.url,
        "title": page.title(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "elements": elements
    }

    json_path = base.with_suffix(".json")
    txt_path = base.with_suffix(".txt")
    png_path = base.with_suffix(".png")

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        page.screenshot(path=str(png_path), full_page=True, timeout=15000)
    except Exception as error:
        print(f"Скриншот не удалось сохранить: {error}")

    lines = []
    lines.append(f"URL: {data['url']}")
    lines.append(f"TITLE: {data['title']}")
    lines.append("")

    for el in data["elements"]:
        lines.append(f"[{el['index']}] {el['tag']} type={el['type']}")
        lines.append(f"  text: {el['text']}")
        lines.append(f"  value: {el['value']}")
        lines.append(f"  nearby: {el['nearby_text']}")
        lines.append(f"  placeholder: {el['placeholder']}")
        lines.append(f"  name: {el['name']}")
        lines.append(f"  id: {el['id']}")
        lines.append(f"  aria-label: {el['aria_label']}")
        lines.append(f"  ng-model: {el['ng_model']}")
        lines.append(f"  ng-click: {el['ng_click']}")
        lines.append(f"  css: {el['css_path']}")
        lines.append(f"  xywh: {el['x']},{el['y']},{el['width']},{el['height']}")
        lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print("Сохранено:")
    print(f"  {json_path}")
    print(f"  {txt_path}")
    print(f"  {png_path}")
    print(f"Найдено элементов: {len(data['elements'])}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=200
        )

        page = browser.new_page()
        page.goto(WARTA_URL, wait_until="domcontentloaded")

        print("Открылся браузер.")
        print("Войдите вручную в Warta и переходите по страницам.")
        print("")
        print("Когда хотите запомнить текущую страницу, вернитесь в CMD и введите имя шага.")
        print("Например:")
        print("  start")
        print("  sprzedaz")
        print("  komunikacyjne")
        print("  oc_graniczne")
        print("  po_sprawdzeniu_numeru")
        print("")
        print("Для выхода введите: q")
        print("")

        while True:
            name = input("Имя снимка страницы или q: ").strip()

            if name.lower() in {"q", "quit", "exit"}:
                break

            if not name:
                name = "page"

            save_inspection(page, name)

        browser.close()


if __name__ == "__main__":
    main()