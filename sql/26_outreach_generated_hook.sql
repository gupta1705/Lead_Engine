-- 26_OUTREACH_GENERATED_HOOK.SQL
-- A model may write the opening sentence. Owner decision, 2026-09-12:
-- "go ahead and build the groq personalisation".
--
-- WHAT CHANGES. Nothing about how an email is approved or sent. The only new
-- thing is that the first sentence of a draft may have been written by a model
-- from that lead's own facts instead of assembled from them, and the row now
-- records which it was and exactly what the model wrote.
--
-- WHY THE ROW RECORDS IT. Batch approval works because every draft in a batch
-- came from the same template, so reading a random few genuinely stands for the
-- rest. A bespoke sentence per email breaks that: each one can be wrong on its
-- own. So a draft with a generated sentence is NOT eligible for batch approval
-- unless the segment explicitly allows it (batch_approval.allow_generated), and
-- when it does, those batches draw a bigger sample. Enforcing that needs the
-- flag on the row, which is why it lives here and not in a log file.
--
-- generated_hook also makes the thing auditable after the fact: the exact
-- sentence is on the row, not buried inside the rendered body.
--
-- DESTRUCTIVE STATEMENTS, reviewed: DROP VIEW (recreated below). No row is
-- deleted, no column is dropped. Run with --allow-destructive.

begin;

alter table outreach add column if not exists generated_hook text;

comment on column outreach.generated_hook is
  'The opening sentence a model wrote for this draft, verbatim, or NULL when '
  'the deterministic hook was used. Non-null means the draft is not eligible '
  'for spot-checked batch approval unless the segment allows it.';

drop view if exists outreach_folders;
create view outreach_folders with (security_invoker = true) as
select
  o.id, o.entity_id, e.name as company, e.domain,
  c.full_name as contact_name, c.email as contact_email,
  o.direction, o.status, o.triage, o.triage_reason,
  o.subject, o.body, o.template_key, o.send_error,
  o.sent_at, o.created_at, o.gmail_thread_id,
  o.sequence_step, o.parent_id, o.stopped_reason,
  o.approved_at, o.approved_by, o.approval_mode, o.spot_checked,
  o.sender_mailbox, o.sender_address,
  o.generated_hook, (o.generated_hook is not null) as generated,
  case
    when o.status = 'drafted'                       then 'drafts'
    when o.status in ('approved','sending')         then 'outbox'
    when o.status = 'sent'                          then 'sent'
    when o.status in ('failed','send_unknown')      then 'attention'
    when o.triage = 'positive'                      then 'positive'
    when o.triage = 'negative'                      then 'negative'
    when o.status in ('received','triaged')         then 'inbox'
    when o.status = 'cancelled'                     then 'cancelled'
    else 'attention'
  end as folder
from outreach o
join entities e on e.id = o.entity_id
left join contacts c on c.id = o.contact_id;

-- the clipping segment turns it on; TVF segments are untouched --------------
-- It stays inert until GROQ_API_KEY exists: with no key every draft falls back
-- to the hook the engine assembles itself, which is the behaviour today.
update segments s
set config = jsonb_set(s.config, '{outreach,generated_hook}', jsonb_build_object(
      'enabled', true,
      'provider', 'groq',
      'model', 'openai/gpt-oss-120b',
      'max_words', 45,
      'max_calls_per_run', 200,
      'requests_per_minute', 25,
      'guidance',
        'The opening sentence of a draft, written by a model from the facts '
        'whitelist in tools/draft_render.facts_for() -- public counts and one '
        'title the lead published, never an address, a contact name or page '
        'text. Every number the model writes must appear in those facts or the '
        'sentence is thrown away and the deterministic hook is used instead; so '
        'is anything with a link, markup, a sales word, or more than two '
        'sentences. No GROQ_API_KEY means no calls and no change. The sentence '
        'is stored on the outreach row, so what a person approved is what is '
        'sent. See tools/llm.py.'))
where s.slug = 'lcx-clipping';

-- and the approval rule that follows from it
update segments s
set config = jsonb_set(s.config, '{outreach,batch_approval}',
      (s.config->'outreach'->'batch_approval')
      || jsonb_build_object(
           'allow_generated', false,
           'generated_sample_fraction', 0.25,
           'generated_guidance',
             'A spot check stands for a batch because every draft in it came '
             'from one template. A model-written sentence can be wrong on its '
             'own, so those drafts are approved one at a time. Set '
             'allow_generated to true once you have read enough of them to '
             'trust it; batches containing them then draw '
             'generated_sample_fraction instead of sample_fraction.'))
where s.slug = 'lcx-clipping'
  and s.config->'outreach' ? 'batch_approval';

commit;

select s.slug,
       s.config->'outreach'->'generated_hook'->>'enabled' as generated_hook,
       s.config->'outreach'->'generated_hook'->>'model' as model,
       s.config->'outreach'->'batch_approval'->>'allow_generated' as batch_allows_generated
from segments s where s.config ? 'outreach' order by s.slug;
