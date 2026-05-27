# Renderer skill subagent (NON-LLM)

The Renderer is a deterministic Jinja2 + python-docx + Playwright wrapper.
It does NOT call Claude. This file exists for symmetry with the other skill
subagents (and to document the renderer's contract for M11+ packs).

The Renderer takes a finalised pack payload + the agency_profile branding +
the appropriate template and produces:

- Markdown deliverables (briefing, agenda, slides as concatenated markdown
  per v0.1 — slide rendering as HTML/PDF/PPTX is V2-PACK-01).
- Word docs for contracts (python-docx).
- HTML decks for proposals (V2-PACK-01; v0.1 markdown only).

The Renderer never writes memos and never has Claude in the loop.
