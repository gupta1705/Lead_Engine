-- A verified From alias belongs to a parent Gmail account, not another login.
-- NULL preserves existing sending behavior. Usage and tokens remain on the parent.
alter table public.user_mailboxes add column if not exists from_address text;
