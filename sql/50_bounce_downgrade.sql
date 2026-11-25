-- 50: a bounce may mark an Apollo-only project's address invalid (2026-11-25).
-- outreach_policy.mark_bounce sets email_status 'invalid' AND verifier 'bounce'; sql/42's check let a downgrade
-- through only when the verifier stayed the same, so every LCX Services reply pull that met a bounce failed
-- (182 failures from 2026-11-23) and its replies were rolled back. Now any downgrade away from 'valid' passes,
-- whatever the verifier; everything else is as in sql/42.
create or replace function enforce_apollo_verified_contact() returns trigger language plpgsql as $$
declare enforced boolean;
begin
    select coalesce(s.config->'sourcing'->>'contacts'='apollo',false) into enforced
    from entities e join segments s on s.id=e.segment_id where e.id=new.entity_id;
    if not coalesce(enforced,false) then return new; end if;
    -- Bounce/verification downgrades are always allowed. They immediately make
    -- the address ineligible, without deleting historical correspondence.
    if tg_op='UPDATE' then
        if new.email is not distinct from old.email and new.entity_id=old.entity_id
           and new.source is not distinct from old.source
           and (new.email_status <> 'valid'
                or (new.verifier is not distinct from old.verifier
                    and new.email_status is not distinct from old.email_status)) then
            return new;
        end if;
    end if;
    -- an address a person typed in for a lead they found (sql/42)
    if new.source = 'manual' and new.verifier = 'person' then
        return new;
    end if;
    if new.source is distinct from 'apollo' or
       (new.email is not null and (new.email_status is distinct from 'valid' or new.verifier is distinct from 'apollo')) then
        raise exception 'This project accepts only Apollo-verified work emails.' using errcode='23514';
    end if;
    return new;
end;
$$;
