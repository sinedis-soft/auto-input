import json
from datetime import datetime
from pathlib import Path


JS_INSPECT = """
() => {
    function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    }

    function textOf(el) {
        if (!el) return '';
        return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    }

    function attr(el, name) {
        return el.getAttribute(name) || '';
    }

    function nearbyText(el) {
        const result = [];

        try {
            if (el.id) {
                const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (label) result.push(textOf(label));
            }
        } catch (e) {}

        const parent = el.closest('div, label, form, section, fieldset, tr, td');
        if (parent) {
            const txt = textOf(parent);
            if (txt && txt.length < 900) result.push(txt);
        }

        let prev = el.previousElementSibling;
        let steps = 0;
        while (prev && steps < 4) {
            const txt = textOf(prev);
            if (txt) result.push(txt);
            prev = prev.previousElementSibling;
            steps++;
        }

        return [...new Set(result)].filter(Boolean).join(' | ');
    }

    function cssPath(el) {
        if (el.id) return `#${CSS.escape(el.id)}`;

        const parts = [];
        let node = el;
        while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 8) {
            let part = node.nodeName.toLowerCase();

            if (node.className && typeof node.className === 'string') {
                const classes = node.className.split(/\\s+/).filter(Boolean).slice(0, 2).map(c => '.' + CSS.escape(c)).join('');
                part += classes;
            }

            const parent = node.parentElement;
            if (parent) {
                const sameTag = Array.from(parent.children).filter(child => child.nodeName === node.nodeName);
                if (sameTag.length > 1) part += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
            }

            parts.unshift(part);
            node = parent;
        }

        return parts.join(' > ');
    }

    const selector = [
        'input','select','textarea','button','a','span',
        '[role="button"]','[role="combobox"]','[role="listbox"]','[role="option"]',
        '[ng-click]','[ng-model]','.dropdown-menu *','.ui-select-choices-row','.select2-results__option'
    ].join(',');

    return {
        url: location.href,
        title: document.title,
        created_at: new Date().toISOString(),
        elements: Array.from(document.querySelectorAll(selector)).filter(visible).map((el, index) => {
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
                ng_options: attr(el, 'ng-options'),
                class: attr(el, 'class'),
                nearby_text: nearbyText(el),
                css_path: cssPath(el),
                x: Math.round(rect.x), y: Math.round(rect.y),
                width: Math.round(rect.width), height: Math.round(rect.height)
            };
        })
    };
}
"""


def safe_filename(text: str) -> str:
    text = text.strip() or "page"
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)[:100]


def save_capture(page, name: str, output_dir: Path = Path("captures")) -> tuple[str, str, str]:
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_dir / f"{timestamp}_{safe_filename(name)}"

    data = page.evaluate(JS_INSPECT)

    json_path = base.with_suffix(".json")
    txt_path = base.with_suffix(".txt")
    png_path = base.with_suffix(".png")

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"URL: {data['url']}", f"TITLE: {data['title']}", ""]
    for el in data["elements"]:
        lines.extend([
            f"[{el['index']}] {el['tag']} type={el['type']}",
            f"  text: {el['text']}",
            f"  value: {el['value']}",
            f"  nearby: {el['nearby_text']}",
            f"  placeholder: {el['placeholder']}",
            f"  name: {el['name']}",
            f"  id: {el['id']}",
            f"  aria-label: {el['aria_label']}",
            f"  ng-model: {el['ng_model']}",
            f"  ng-click: {el['ng_click']}",
            f"  ng-options: {el['ng_options']}",
            f"  css: {el['css_path']}",
            f"  xywh: {el['x']},{el['y']},{el['width']},{el['height']}",
            "",
        ])
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    page.screenshot(path=str(png_path), full_page=True, timeout=15000)

    return str(json_path), str(txt_path), str(png_path)
