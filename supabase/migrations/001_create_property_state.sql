create table if not exists property_state (
  property_id text primary key,
  price integer not null,
  address text not null default '',
  url text not null default '',
  bedrooms integer not null default 0,
  property_type text not null default '',
  first_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

grant select, insert, update on public.property_state to service_role;

alter table property_state enable row level security;

create policy "service_role_all"
  on property_state
  for all
  to service_role
  using (true)
  with check (true);
