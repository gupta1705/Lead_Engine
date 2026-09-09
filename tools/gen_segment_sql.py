#!/usr/bin/env python3
"""gen_segment_sql.py -- a segment's config JSON as an idempotent SQL file.

    python tools/gen_segment_sql.py lcx-clipping
      -> sql/03d_segment_lcx_clipping.sql  (from config/segment.lcx-clipping.json)

Every segment is a config row. The JSON under config/ is the source of truth;
the SQL file is how it reaches the database (python tools/run_sql.py <file>)
and the record of what was applied. Never hand-edit the generated literal:
edit the JSON, regenerate, run. Re-running the SQL updates the row in place.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = {                       # slug -> (sql file, name, entity_type)
    "startup-acquisitions": "03c_segment_startup_acquisitions.sql",
    "lcx-clipping": "03d_segment_lcx_clipping.sql",
}
NAMES = {
    "startup-acquisitions": "Startup Acquisition Targets -- creator tools & media-tech",
    "lcx-clipping": "LCX Clipping -- creators and podcasters with a back catalogue",
}


def render(slug, cfg):
    literal = json.dumps(cfg, indent=2, ensure_ascii=False).replace("'", "''")
    name = NAMES.get(slug, cfg.get("ui", {}).get("project_name", slug))
    return f"""-- {FILES[slug].upper()}
-- Segment config row for '{slug}'. GENERATED from config/segment.{slug}.json
-- by tools/gen_segment_sql.py; edit the JSON, regenerate, never hand-edit this
-- literal. Idempotent: an existing row is updated to the file's content.
insert into segments (slug, name, entity_type, config)
values (
  '{slug}',
  '{name.replace("'", "''")}',
  '{cfg["entity_type"]}',
  '{literal}'::jsonb
)
on conflict (slug) do update
  set name = excluded.name,
      entity_type = excluded.entity_type,
      config = excluded.config,
      updated_at = now();

select slug, entity_type,
       jsonb_array_length(config->'rubric')  as rubric_criteria,
       jsonb_array_length(config->'gates')   as gates,
       config->>'score_threshold_review'     as review_at,
       config->>'score_threshold_priority'   as priority_at
from segments order by slug;
"""


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in FILES:
        sys.exit("usage: gen_segment_sql.py <slug>   one of: " + ", ".join(FILES))
    slug = sys.argv[1]
    cfg = json.loads((ROOT / "config" / ("segment.%s.json" % slug)).read_text(encoding="utf-8"))
    out = ROOT / "sql" / FILES[slug]
    out.write_text(render(slug, cfg), encoding="utf-8")
    print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
