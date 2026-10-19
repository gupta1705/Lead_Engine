-- Unaddressed copy can be reviewed as a draft. Any assigned recipient must
-- still be Apollo-verified, and approval/sending always require that recipient.
-- Clipping has no Apollo contact policy and keeps its existing behavior.
create or replace function enforce_apollo_outreach_contact() returns trigger language plpgsql
set search_path = public, pg_temp as $$
begin
    if new.direction='outbound'
       and (new.status in ('approved','sending') or (new.status='drafted' and new.contact_id is not null))
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
