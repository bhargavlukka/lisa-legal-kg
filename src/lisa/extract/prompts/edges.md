PROMPT_VERSION: edges-v1
You build a legal knowledge graph from US court and agency decisions. You receive the case text (pages marked
`===== [[PAGE n | ...]] =====`) and a NODE CATALOG of nodes already extracted from it. Extract the relations
(edges) between catalog nodes that the text states or clearly implies.

## Relations
- `presents_issue` opinion -> issue; `states_fact` opinion -> fact; `states_rule` opinion -> rule;
  `holds` opinion -> holding; `has_outcome` opinion -> outcome
- `supports` reasoning -> holding
- `applies_rule` holding or reasoning -> rule
- `relies_on` reasoning, rule, holding or fact -> authority_ref. Set `stance`:
  `follows` (treated as controlling and applied), `distinguishes` (held not to apply on these facts),
  `overrules` (expressly overruled), `criticizes` (disapproved but not overruled),
  `relies_on` (cited as support), `cites_without_treatment` (mentioned only)
- `relevant_to` fact -> issue; `resolves` holding -> issue
- `agrees_with` / `disagrees_with` between items of different opinion parts (e.g. a dissent's holding disagrees
  with the majority's holding)

Only these (source type, relation, target type) combinations are allowed:
{{SIGNATURES}}

## Fields of every edge
`source`, `target` (catalog ids, copied exactly), `relation`, `stance` (relies_on only, else null),
`basis` (`explicit` if the text says it, `inferred` if you infer it; inferred edges need
attrs.inference_reason), `part`, `evidence` (1 item `{"page": n, "quote": "..."}`, 8 to 30 consecutive words copied
exactly from one page), `confidence` (0 to 1), `attrs`.

## Rules
- Use only ids from the catalog. Only output edges whose source id is listed under SOURCE NODES.
- Reply with a single JSON object `{"edges": [...]}` and nothing else.

{{FEWSHOT}}
