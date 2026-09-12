-- 25_outreach_footer.sql -- one editable footer per segment, and more of the
-- lead's own evidence in the clipping templates.
--
-- WHY. The sign-off, the postal address and the opt-out line were copied into
-- every template body. That is the part of an email that must be right on ALL
-- of them, so it belongs in one place a person can edit -- config
-- outreach.footer.text, edited from the app (Outreach -> Footer). Templates
-- now end with {{footer}}.
--
-- Nothing about what goes out changes here: the footer text is lifted from
-- what the templates already said, character for character, so a draft
-- rendered after this file renders exactly as it did before it.
--
-- Idempotent: a segment that already has outreach.footer is left alone, and
-- the template rewrite only touches bodies that still carry {{sender_name}}.

begin;

-- 1. the footer block, taken from what the templates already say --------------
--    (everything from {{sender_name}} to the end of the first template body)
with tail as (
  select distinct on (s.id) s.id,
         substring(e.el->>'body' from '\{\{sender_name\}\}.*$') as text
  from segments s,
       lateral jsonb_array_elements(s.config->'outreach'->'templates')
               with ordinality as e(el, ord)
  where s.config ? 'outreach'
    and not (s.config->'outreach' ? 'footer')
    and e.el->>'body' like '%{{sender_name}}%'
  order by s.id, e.ord
)
update segments s
set config = jsonb_set(s.config, '{outreach,footer}', jsonb_build_object(
      'text', tail.text,
      'guidance', 'The last block of every email in this segment. Edited in the app: '
                  'Outreach -> Footer. It may use {{sender_name}}, {{sender_title}}, '
                  '{{sender_email}}, {{postal_address}}, {{company}} and {{greeting_name}}, '
                  'and it is refused unless it carries a postal address and a way out -- '
                  'both are required of commercial email and both are what keep a sending '
                  'domain alive. Templates end with {{footer}}; see tools/draft_render.py.'))
from tail
where tail.id = s.id;

-- 2. templates end with {{footer}} --------------------------------------------
with rewritten as (
  select s.id,
         jsonb_agg(
           case when e.el->>'body' like '%{{sender_name}}%'
                then jsonb_set(e.el, '{body}', to_jsonb(
                       regexp_replace(e.el->>'body', '\{\{sender_name\}\}.*$', '{{footer}}')))
                else e.el end
           order by e.ord) as arr
  from segments s,
       lateral jsonb_array_elements(s.config->'outreach'->'templates')
               with ordinality as e(el, ord)
  where s.config ? 'outreach'
  group by s.id
)
update segments s
set config = jsonb_set(s.config, '{outreach,templates}', rewritten.arr)
from rewritten
where rewritten.id = s.id;

-- 3. the clipping templates name the lead's own work ---------------------------
--    {{latest_work}} is their most recent episode BY NAME when we know it and
--    it is still recent, otherwise a phrase that names nothing. {{clip_math}}
--    turns their own average length into a number of shorts. Both are built
--    from the lead's metadata in tools/draft_render.py -- no model writes
--    prose, so a draft cannot claim what the row does not support.
update segments s
set config = jsonb_set(s.config, '{outreach,templates}', t.arr)
from (
  select s2.id,
         jsonb_agg(
           jsonb_set(e.el, '{body}', to_jsonb(
             replace(replace(replace(e.el->>'body',
               'reply "yes" and we''ll clip your latest episode into three shorts, free,',
               'reply "yes" and we''ll cut three shorts out of {{latest_work}}, free,'),
               'reply "yes" and we''ll clip one piece from your channel into three shorts, free,',
               'reply "yes" and we''ll cut three shorts out of {{latest_work}}, free,'),
               'The offer stands: reply "yes" and we''ll cut three shorts from one of your recent long videos or episodes, free, so you can judge the quality before anything else is discussed.',
               'To put a number on it: {{clip_math}}. The offer stands -- reply "yes" and we''ll cut three out of {{latest_work}}, free, so you can judge the quality before anything else is discussed.')))
           order by e.ord) as arr
  from segments s2,
       lateral jsonb_array_elements(s2.config->'outreach'->'templates')
               with ordinality as e(el, ord)
  where s2.slug = 'lcx-clipping'
  group by s2.id) t
where t.id = s.id;

-- 4. say so in the segment's own guidance -------------------------------------
update segments s
set config = jsonb_set(s.config, '{outreach,guidance}', to_jsonb(
      (s.config->'outreach'->>'guidance') ||
      ' The footer -- sign-off, postal address, opt-out -- is one setting for the'
      ' whole segment (outreach.footer.text), edited in the app under Outreach ->'
      ' Footer; templates end with {{footer}}.'))
where s.config ? 'outreach'
  and s.config->'outreach' ? 'guidance'
  and position('outreach.footer.text' in (s.config->'outreach'->>'guidance')) = 0;

commit;

-- what it looks like afterwards
select s.slug,
       left(s.config->'outreach'->'footer'->>'text', 60) as footer_starts,
       count(*) filter (where e.el->>'body' like '%{{footer}}%') as templates_with_footer,
       count(*) as templates
from segments s,
     lateral jsonb_array_elements(s.config->'outreach'->'templates') as e(el)
where s.config ? 'outreach'
group by s.slug, s.config->'outreach'->'footer'->>'text'
order by s.slug;
