-- 27_AUTO_SHORTLIST.SQL
-- Owner decision, 2026-09-14: "Instead of shortlisting i want you to
-- automatically shortlist anyone with score above 20."
--
-- Turns the rule on for the LCX clipping segment only. The rule itself lives in
-- sql/14_auto_shortlist.sql, the last step of the promote chain, so it runs
-- after every refresh and every re-score. TVF segments keep shortlisting by
-- hand: their config carries no auto_shortlist block.
--
-- Not destructive: one config key is set. Idempotent.

begin;

update segments s
set config = jsonb_set(s.config, '{auto_shortlist}', jsonb_build_object(
      'enabled', true,
      'min_score', 20,
      'guidance',
        'Owner decision 2026-09-14. Every ready_for_review lead with fit_score '
        'strictly above min_score is shortlisted by the last step of the promote '
        'chain (sql/14_auto_shortlist.sql) instead of by hand. Rejected, archived '
        'and contacted rows are never touched, and a lead a person moves back to '
        'review is never shortlisted again (metadata.auto_shortlisted_at). '
        'Shortlisting sends nothing: every draft still needs approval. Set '
        'enabled to false to go back to shortlisting by hand.'))
where s.slug = 'lcx-clipping';

commit;

select s.slug,
       s.config->'auto_shortlist'->>'enabled' as auto_shortlist,
       s.config->'auto_shortlist'->>'min_score' as min_score
from segments s order by s.slug;
