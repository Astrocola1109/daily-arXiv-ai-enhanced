-- Personal digest schema. Run once in a fresh Supabase project.
-- Set the owner only in the SQL editor after creating the Auth user.
begin;
create table public.digest_owners (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.digest_owners enable row level security;
revoke all on public.digest_owners from anon, authenticated;

create function public.is_digest_owner() returns boolean
language sql stable security definer set search_path = ''
as $$ select exists (select 1 from public.digest_owners where user_id = (select auth.uid())); $$;
revoke all on function public.is_digest_owner() from public;
grant execute on function public.is_digest_owner() to authenticated;

create table public.papers (
  user_id uuid not null references auth.users(id) on delete cascade,
  paper_id text not null,
  version_id text not null,
  announcement_date date not null,
  payload jsonb not null,
  primary key (user_id, version_id)
);
create index papers_day on public.papers(user_id, announcement_date desc);
create table public.digests (
  user_id uuid not null references auth.users(id) on delete cascade,
  day date not null,
  payload jsonb not null,
  primary key (user_id, day)
);
create table public.reading_states (
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  paper_id text not null,
  favorite boolean not null default false,
  is_read boolean not null default false,
  disliked boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (user_id, paper_id)
);
create table public.research_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  profile jsonb not null check (jsonb_typeof(profile->'research_lines') = 'array'),
  proposal jsonb,
  updated_at timestamptz not null default now()
);

alter table public.papers enable row level security;
alter table public.digests enable row level security;
alter table public.reading_states enable row level security;
alter table public.research_profiles enable row level security;
revoke all on public.papers, public.digests, public.reading_states, public.research_profiles from anon, authenticated;
grant select on public.papers, public.digests, public.research_profiles to authenticated;
grant select, insert, update, delete on public.reading_states to authenticated;
grant update (profile, proposal, updated_at) on public.research_profiles to authenticated;
grant all on public.papers, public.digests, public.reading_states, public.research_profiles, public.digest_owners to service_role;

create policy owner_read_papers on public.papers for select to authenticated
using (user_id=(select auth.uid()) and (select public.is_digest_owner()));
create policy owner_read_digests on public.digests for select to authenticated
using (user_id=(select auth.uid()) and (select public.is_digest_owner()));
create policy owner_states on public.reading_states for all to authenticated
using (user_id=(select auth.uid()) and (select public.is_digest_owner()))
with check (user_id=(select auth.uid()) and (select public.is_digest_owner()));
create policy owner_read_profile on public.research_profiles for select to authenticated
using (user_id=(select auth.uid()) and (select public.is_digest_owner()));
create policy owner_update_profile on public.research_profiles for update to authenticated
using (user_id=(select auth.uid()) and (select public.is_digest_owner()))
with check (user_id=(select auth.uid()) and (select public.is_digest_owner()));

-- Atomic per-flag update avoids overwriting a different flag changed on another device.
create function public.set_reading_flag(p_paper_id text, p_flag text, p_value boolean)
returns setof public.reading_states language plpgsql security invoker set search_path = ''
as $$
begin
  if p_flag not in ('favorite','is_read','disliked') then raise exception 'Invalid reading flag'; end if;
  if not public.is_digest_owner() then raise exception 'Not authorized'; end if;
  return query insert into public.reading_states(user_id,paper_id,favorite,is_read,disliked)
  values (auth.uid(),p_paper_id,case when p_flag='favorite' then p_value else false end,
    case when p_flag='is_read' then p_value else false end,case when p_flag='disliked' then p_value else false end)
  on conflict (user_id,paper_id) do update set
    favorite=case when p_flag='favorite' then p_value else reading_states.favorite end,
    is_read=case when p_flag='is_read' then p_value else reading_states.is_read end,
    disliked=case when p_flag='disliked' then p_value else reading_states.disliked end,
    updated_at=now()
  returning *;
end; $$;
revoke all on function public.set_reading_flag(text,text,boolean) from public;
grant execute on function public.set_reading_flag(text,text,boolean) to authenticated;
commit;

-- After creating your own Auth user, replace the UUID and execute:
-- insert into public.digest_owners(user_id) values ('YOUR-AUTH-USER-UUID');
-- Do not put service_role keys, SMTP credentials, or private data in Pages.
