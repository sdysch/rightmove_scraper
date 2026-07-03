create table price_history (
    id bigserial primary key,
    property_id text not null,
    price integer not null,
    previous_price integer,
    address text,
    url text,
    bedrooms integer,
    property_type text,
    changed_at timestamptz not null default now()
);

create index idx_price_history_property_id on price_history (property_id);
create index idx_price_history_changed_at on price_history (changed_at);
