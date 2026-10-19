-- Apollo-only projects may use only addresses Apollo has verified. Historical
-- contacts remain visible, but cannot qualify, be drafted, approved or sent.
-- Clipping has no Apollo contact policy and retains its existing behavior.
create or replace function contact_allowed(p_entity uuid, p_source text, p_verifier text, p_status text)
returns boolean language sql stable as $$
    select not exists (
        select 1 from entities e join segments s on s.id=e.segment_id
        where e.id=p_entity and s.config->'sourcing'->>'contacts'='apollo'
    ) or (coalesce(p_source='apollo',false) and coalesce(p_verifier='apollo',false)
          and coalesce(p_status='valid',false))
$$;

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
           and new.source is not distinct from old.source and new.verifier is not distinct from old.verifier
           and (new.email_status is not distinct from old.email_status or new.email_status <> 'valid') then
            return new;
        end if;
    end if;
    if new.source is distinct from 'apollo' or
       (new.email is not null and (new.email_status is distinct from 'valid' or new.verifier is distinct from 'apollo')) then
        raise exception 'This project accepts only Apollo-verified work emails.' using errcode='23514';
    end if;
    return new;
end;
$$;
create or replace trigger contact_apollo_verified
before insert or update of entity_id,email,email_status,source,verifier on contacts
for each row execute function enforce_apollo_verified_contact();

create or replace function enforce_apollo_outreach_contact() returns trigger language plpgsql as $$
begin
    if new.direction='outbound' and new.status in ('drafted','approved','sending')
       and exists (select 1 from entities e join segments s on s.id=e.segment_id
                   where e.id=new.entity_id and s.config->'sourcing'->>'contacts'='apollo')
       and not exists (select 1 from contacts c where c.id=new.contact_id and c.entity_id=new.entity_id
                       and c.email is not null and contact_allowed(c.entity_id,c.source,c.verifier,c.email_status)) then
        raise exception 'Apollo must verify the recipient email before outreach.' using errcode='23514';
    end if;
    if new.direction='outbound' and coalesce(new.sequence_step,0)=0 and new.status in ('drafted','approved','sending')
       and exists (select 1 from entities e join segments s on s.id=e.segment_id
                   where e.id=new.entity_id and s.config->'sourcing'->>'contacts'='apollo'
                   and s.config ? 'lead_service'
                   and (new.service is null or new.service is distinct from
                       coalesce(e.metadata#>>'{lead_service,service}',e.metadata#>>'{lead_service,name}'))) then
        raise exception 'The lead service changed; create and review a fresh draft.' using errcode='23514';
    end if;
    return new;
end;
$$;
create or replace trigger outreach_apollo_verified
before insert or update of status,contact_id,entity_id on outreach
for each row execute function enforce_apollo_outreach_contact();
