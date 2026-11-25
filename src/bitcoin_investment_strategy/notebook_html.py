"""Strip committed notebook outputs and export executed notebooks to static HTML."""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
from typing import Any

from jinja2 import Environment, select_autoescape
import nbformat


NOTEBOOK_TITLES = {
    "bitcoin_savings_plan.ipynb": (
        "Bitcoin Savings Plan",
        "Saving a fixed share of income in bitcoin: what the plan has done to date.",
    ),
    "bitcoin_supply_dynamics.ipynb": (
        "Bitcoin Supply Dynamics",
        "Issuance, coin age, holder cohorts, and realized profit and loss.",
    ),
    "bitcoin_demand_dynamics.ipynb": (
        "Bitcoin Demand Dynamics",
        "Miners, on-chain participation, US spot ETFs, corporate and sovereign treasuries, and price models.",
    ),
}


def strip_notebook_outputs(notebook: dict[str, Any]) -> dict[str, Any]:
    """Remove all cell outputs and execution counts in-place, returning the notebook."""
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        metadata = cell.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("execution", None)
    return notebook


def strip_notebook_file(path: Path) -> None:
    """Strip outputs and execution counts from an .ipynb file on disk."""
    notebook = nbformat.read(path, as_version=4)
    strip_notebook_outputs(notebook)
    nbformat.write(notebook, path)


def is_notebook_stripped(path: Path) -> bool:
    """Return True iff every code cell in the notebook has empty outputs and null execution_count."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for cell in data.get("cells", []):
        if cell.get("cell_type") == "code":
            if cell.get("outputs"):
                return False
            if cell.get("execution_count") is not None:
                return False
    return True


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    return escaped


def _render_markdown(source: str) -> str:
    """Render common notebook markdown blocks (headings, lists, tables, rules, paragraphs)."""
    lines = source.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped in {"---", "***", "___"}:
            blocks.append("<hr>")
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline_markdown(heading.group(2).strip())}</h{level}>")
            i += 1
            continue
        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            continue
        if (
            "|" in stripped
            and i + 1 < len(lines)
            and re.match(r"^\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1].strip())
        ):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            body_rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                body_rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head_html = "".join(f"<th>{_inline_markdown(c)}</th>" for c in header_cells)
            rows_html = "".join(
                "<tr>" + "".join(f"<td>{_inline_markdown(c)}</td>" for c in row) + "</tr>"
                for row in body_rows
            )
            blocks.append(f"<table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table>")
            continue
        if re.match(r"^[-*]\s+", stripped):
            items: list[str] = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            items_html = "".join(f"<li>{_inline_markdown(item)}</li>" for item in items)
            blocks.append(f"<ul>{items_html}</ul>")
            continue
        para_lines = [stripped]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", "```", "- ", "* ", "---"))
            and not ("|" in lines[i] and i + 1 < len(lines) and "---" in lines[i + 1])
        ):
            para_lines.append(lines[i].strip())
            i += 1
        blocks.append(f"<p>{_inline_markdown(' '.join(para_lines))}</p>")
    return "\n".join(blocks)


def _join_text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return "" if value is None else str(value)


def _render_output(output: dict[str, Any]) -> dict[str, str] | None:
    kind = output.get("output_type")
    if kind == "stream":
        text = _join_text(output.get("text", ""))
        if not text:
            return None
        return {"kind": "stream", "content": text}
    if kind in {"display_data", "execute_result"}:
        data = output.get("data", {})
        if "image/png" in data:
            encoded = _join_text(data["image/png"]).replace("\n", "")
            return {"kind": "png", "content": encoded}
        if "image/svg+xml" in data:
            return {"kind": "html", "content": _join_text(data["image/svg+xml"])}
        if "text/html" in data:
            return {"kind": "html", "content": _join_text(data["text/html"])}
        if "text/plain" in data:
            text = _join_text(data["text/plain"])
            if text and not text.startswith("<Figure size"):
                return {"kind": "text", "content": text}
    if kind == "error":
        traceback_lines = output.get("traceback") or [
            f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
        ]
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(traceback_lines))
        return {"kind": "error", "content": cleaned}
    return None


_ENV = Environment(autoescape=select_autoescape(["html", "xml"]))

_NOTEBOOK_TEMPLATE = _ENV.from_string("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} · Secret Satoshis</title>
<style>
  :root {
    --bg: #08080c;
    --surface: #0e0e16;
    --border: #2a2a42;
    --primary: #e4e4ef;
    --secondary: #9090a8;
    --orange: #f7931a;
    --red: #f07d82;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.65;
  }
  header {
    border-bottom: 1px solid var(--border);
    padding: 1.25rem 1.5rem;
    background: var(--surface);
  }
  .header-inner, main {
    max-width: 1080px;
    margin: 0 auto;
  }
  .brand {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.82rem;
    letter-spacing: 0.08em;
    color: var(--secondary);
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .brand a { color: var(--orange); text-decoration: none; }
  h1, h2, h3, h4 { color: var(--primary); margin-top: 1.8rem; }
  h1 { border-bottom: 2px solid var(--orange); padding-bottom: 0.4rem; }
  a { color: var(--orange); }
  main { padding: 1.5rem; }
  .cell { margin-bottom: 1.5rem; }
  details.code-cell {
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    margin-bottom: 0.75rem;
  }
  details.code-cell summary {
    cursor: pointer;
    padding: 0.45rem 0.85rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.8rem;
    color: var(--secondary);
  }
  pre {
    margin: 0;
    padding: 0.85rem 1rem;
    overflow-x: auto;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.84rem;
    line-height: 1.45;
  }
  .output-stream, .output-text {
    background: var(--surface);
    border-left: 3px solid var(--border);
    border-radius: 4px;
    margin-top: 0.5rem;
  }
  .output-error {
    background: #1c1015;
    border-left: 3px solid var(--red);
    color: var(--red);
    margin-top: 0.5rem;
  }
  .output-figure {
    margin: 0.75rem 0;
    text-align: center;
  }
  .output-figure img {
    max-width: 100%;
    height: auto;
    border-radius: 4px;
  }
  .output-html {
    overflow-x: auto;
    margin: 0.75rem 0;
  }
  table {
    border-collapse: collapse;
    width: 100%;
    margin: 1rem 0;
    font-size: 0.9rem;
  }
  th, td {
    border-bottom: 1px solid var(--border);
    padding: 0.55rem 0.75rem;
    text-align: left;
  }
  thead th {
    background: var(--surface);
    color: var(--orange);
    border-top: 2px solid var(--orange);
  }
  hr { border: 0; border-top: 1px solid var(--border); margin: 2rem 0; }
  code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.88em;
    background: var(--surface);
    padding: 0.1rem 0.3rem;
    border-radius: 3px;
  }
  pre code { background: transparent; padding: 0; }
</style>
</head>
<body>
<header>
  <div class="header-inner">
    <div class="brand">
      <span><a href="index.html">SECRET SATOSHIS</a> · BITCOIN INVESTMENT STRATEGY</span>
      <span>Data through {{ data_end }}</span>
    </div>
  </div>
</header>
<main>
{% for cell in cells %}
  <section class="cell cell-{{ cell.cell_type }}">
  {% if cell.cell_type == 'markdown' %}
    {{ cell.html | safe }}
  {% else %}
    {% if cell.source %}
    <details class="code-cell">
      <summary>Code cell {{ cell.index }}</summary>
      <pre><code>{{ cell.source }}</code></pre>
    </details>
    {% endif %}
    {% for out in cell.outputs %}
      {% if out.kind == 'png' %}
      <div class="output-figure"><img src="data:image/png;base64,{{ out.content }}" alt="Notebook chart"></div>
      {% elif out.kind == 'html' %}
      <div class="output-html">{{ out.content | safe }}</div>
      {% elif out.kind == 'error' %}
      <pre class="output-error">{{ out.content }}</pre>
      {% else %}
      <pre class="output-{{ out.kind }}">{{ out.content }}</pre>
      {% endif %}
    {% endfor %}
  {% endif %}
  </section>
{% endfor %}
</main>
</body>
</html>
""")

_INDEX_TEMPLATE = _ENV.from_string("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bitcoin Investment Strategy · Secret Satoshis</title>
<style>
  :root {
    --bg: #08080c;
    --surface: #0e0e16;
    --border: #2a2a42;
    --primary: #e4e4ef;
    --secondary: #9090a8;
    --orange: #f7931a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.6;
  }
  main { max-width: 860px; margin: 0 auto; padding: 3rem 1.5rem; }
  .eyebrow {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.82rem;
    letter-spacing: 0.08em;
    color: var(--orange);
  }
  h1 { margin: 0.5rem 0 0.75rem; font-size: 2rem; }
  .meta { color: var(--secondary); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.88rem; }
  .cards { display: grid; gap: 1rem; margin-top: 2rem; }
  .card {
    display: block;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.25rem 1.5rem;
    text-decoration: none;
    color: inherit;
  }
  .card:hover { border-color: var(--orange); }
  .card h2 { margin: 0 0 0.35rem; color: var(--orange); font-size: 1.2rem; }
  .card p { margin: 0; color: var(--secondary); }
</style>
</head>
<body>
<main>
  <div class="eyebrow">SECRET SATOSHIS · DAILY RENDERED NOTEBOOKS</div>
  <h1>Bitcoin Investment Strategy</h1>
  <div class="meta">Data through {{ data_end }}</div>
  <div class="cards">
  {% for item in items %}
    <a class="card" href="{{ item.href }}">
      <h2>{{ item.title }}</h2>
      <p>{{ item.description }}</p>
    </a>
  {% endfor %}
  </div>
</main>
</body>
</html>
""")


def render_notebook_html(notebook: dict[str, Any], *, title: str, data_end: str) -> str:
    """Render an executed nbformat v4 notebook dict to standalone HTML."""
    rendered_cells: list[dict[str, Any]] = []
    code_index = 0
    for cell in notebook.get("cells", []):
        cell_type = cell.get("cell_type")
        source = _join_text(cell.get("source", ""))
        if cell_type == "markdown":
            rendered_cells.append({"cell_type": "markdown", "html": _render_markdown(source)})
        elif cell_type == "code":
            code_index += 1
            outputs = [
                rendered
                for raw in cell.get("outputs", [])
                if (rendered := _render_output(raw)) is not None
            ]
            rendered_cells.append({
                "cell_type": "code",
                "index": code_index,
                "source": source.strip(),
                "outputs": outputs,
            })
    return _NOTEBOOK_TEMPLATE.render(title=title, data_end=data_end, cells=rendered_cells)


def export_notebooks_html(
    executed_notebooks: list[Path],
    html_dir: Path,
    *,
    data_end: str,
) -> list[Path]:
    """Export executed .ipynb files to HTML plus index.html and .nojekyll for GitHub Pages."""
    html_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index_items: list[dict[str, str]] = []
    for nb_path in executed_notebooks:
        notebook = nbformat.read(nb_path, as_version=4)
        title, description = NOTEBOOK_TITLES.get(
            nb_path.name,
            (nb_path.stem.replace("_", " ").title(), "Rendered notebook output."),
        )
        out_name = f"{nb_path.stem}.html"
        out_path = html_dir / out_name
        out_path.write_text(
            render_notebook_html(notebook, title=title, data_end=data_end),
            encoding="utf-8",
        )
        written.append(out_path)
        index_items.append({"href": out_name, "title": title, "description": description})
    index_path = html_dir / "index.html"
    index_path.write_text(
        _INDEX_TEMPLATE.render(data_end=data_end, items=index_items),
        encoding="utf-8",
    )
    (html_dir / ".nojekyll").write_text("", encoding="utf-8")
    written.append(index_path)
    return written
