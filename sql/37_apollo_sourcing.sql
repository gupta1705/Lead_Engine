-- Enforce the configured Apollo-only intake policy on new leads and contacts.
-- Existing records and clipping are preserved. Invoker rights; no new grants.
create or replace function enforce_apollo_lead_source() returns trigger as $$
declare policy jsonb;
begin
    select config->'sourcing' into policy from segments where id = new.segment_id;
    if policy->>'provider' = 'apollo'
       and not (coalesce(policy->'allowed_sources', '[]'::jsonb) ? new.source) then
        raise exception 'This project accepts new leads only from Apollo.' using errcode = '23514';
    end if;
    return new;
end;
$$ language plpgsql;

create or replace trigger staging_apollo_source
before insert or update of source, segment_id on staging_candidates
for each row execute function enforce_apollo_lead_source();

create or replace trigger entity_apollo_source
before insert or update of source, segment_id on entities
for each row execute function enforce_apollo_lead_source();

create or replace function enforce_apollo_contact_source() returns trigger as $$
declare policy jsonb;
begin
    select s.config->'sourcing' into policy
      from entities e join segments s on s.id = e.segment_id where e.id = new.entity_id;
    if policy->>'contacts' = 'apollo' and new.source is distinct from 'apollo' then
        raise exception 'This project accepts new contacts only from Apollo.' using errcode = '23514';
    end if;
    return new;
end;
$$ language plpgsql;

create or replace trigger contact_apollo_source
before insert on contacts for each row execute function enforce_apollo_contact_source();
