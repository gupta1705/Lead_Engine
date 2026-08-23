-- 07A_P1_DISPOSITIONS.SQL
-- P3 -- the first review, dispositioned. Owner call, 2026-08-23.
--
-- THE RULE THE OWNER SET: reject below 25, accept everything else. Applied
-- against the scores produced after the zero-unverified change (04b), with the
-- thresholds revamped in the same sitting to review = 25 / priority = 60.
--
-- Rejections carry a reason, always. Not ceremony: at the P11 checkpoint the
-- rejection reasons get read as a GROUP, and a pattern across them is the
-- signal that a rubric weight is wrong. "Rejected" with no reason contributes
-- nothing to that and cannot be audited later either.
--
-- Matched on name rather than uuid so this file stays readable and survives a
-- re-seed. Names are unique per segment (uq_entities_segment_name_nodomain and
-- the domain index between them guarantee it in practice).

----------------------------------------------------------------------
-- SHORTLISTED -- 7 candidates at or above 25
----------------------------------------------------------------------
update entities
set status = 'shortlisted'
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1'
  and name in (
    'Tonko House',              -- 63.27  priority band; only verified international co-pro
    'Lowbrow Studios',          -- 53.64
    'Meerkat Media',            -- 40.00
    'Neon Zoo',                 -- 40.00
    'Chiodo Bros. Productions', -- 40.00
    'Exit 73 Studios',          -- 37.73
    'Minnow Mountain'           -- 26.82  see note below
  );

----------------------------------------------------------------------
-- REJECTED -- 3 candidates below 25, each with a reason
----------------------------------------------------------------------
update entities
set status = 'rejected',
    status_reason = 'Below the 25-point floor at 14.09. Indie feature and branded-content producer operating outside the TVF genre lanes, with no verified IP-adaptation history and no standing platform output relationship. Sundance pathway is real but points away from format co-production.'
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1' and name = 'Tandem Pictures';

update entities
set status = 'rejected',
    status_reason = 'Below the 25-point floor at 13.18. Title design and network branding is work-for-hire craft with no owned IP, so client_work_dominance takes the full penalty and genre_fit scores zero. A potential vendor for finishing TVF originals, not a co-production partner.'
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1' and name = 'Block & Tackle';

update entities
set status = 'rejected',
    status_reason = 'Below the 25-point floor at 5.00, the lowest in the batch. Forty years of brand-character advertising for client-owned properties, no streamer or network output relationship, and no owned IP beyond occasional shorts. Right size, wrong shape entirely. Their contact page also refuses unsolicited proposals.'
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1' and name = 'Calabash';

----------------------------------------------------------------------
-- APPROVAL RATE #1 -- the number P11 will be measured against
----------------------------------------------------------------------
select
  count(*) filter (where status = 'shortlisted') as shortlisted,
  count(*) filter (where status = 'rejected')    as rejected,
  round(100.0 * count(*) filter (where status = 'shortlisted')
        / nullif(count(*) filter (where status in ('shortlisted','rejected')), 0), 1)
    as approval_rate_pct
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1';

----------------------------------------------------------------------
-- The queue should now be empty.
----------------------------------------------------------------------
select count(*) as still_in_queue from review_queue;

-- NOTE ON MINNOW MOUNTAIN (26.82, shortlisted by 1.82 points): it clears the
-- floor only because revenue_above_cap was graded 1.0 on a RocketReach estimate
-- of ~$10.4M that the source research itself calls implausible for a six-person
-- core -- almost certainly Undone and Apollo production budgets flowing through
-- the LLC. That single input costs it 20 points. If a reviewer ever downgrades
-- it to 0, Minnow scores 46.82 and sits fourth in the batch rather than seventh.
-- Flagged here because a lead surviving on the strength of a number nobody
-- believes is worth revisiting before it gets contacted at P20.
