-- Walk Safety: Google connection, trusted contacts, email escalation.
-- Run once in Supabase -> SQL Editor (safe to re-run: everything is "if not exists").
--
-- Only the FastAPI backend talks to these tables, using the secret (service role) key.
-- Row Level Security is ON with no policies, so the public/publishable key can read nothing.

-- The person's connected Google account (one row per person; this prototype uses 'default').
create table if not exists public.google_accounts (
  id                uuid primary key default gen_random_uuid(),
  person_key        text not null unique default 'default',
  person_name       text,
  google_email      text not null,
  refresh_token_enc text not null,              -- Fernet-encrypted; key lives only in backend/.env
  scopes            text[] not null default '{}',
  status            text not null default 'connected'
                      check (status in ('connected', 'needs_reconnect')),
  connected_at      timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- Trusted contacts, emailed in priority order (1 = first).
create table if not exists public.contacts (
  id            uuid primary key default gen_random_uuid(),
  person_key    text not null default 'default',
  name          text not null,
  email         text not null,
  relationship  text,
  priority      int  not null check (priority >= 1),
  photo_url     text,
  source        text not null default 'manual' check (source in ('manual', 'google')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (person_key, priority),
  unique (person_key, email)
);

-- One row per alert episode (see docs/superpowers/specs/2026-11-21-google-escalation-design.md).
create table if not exists public.escalations (
  id               uuid primary key default gen_random_uuid(),
  person_key       text not null default 'default',
  journey_id       text not null,
  tier             text not null check (tier in ('person', 'sequential', 'all')),
  status           text not null default 'open' check (status in ('open', 'acknowledged', 'closed')),
  next_priority    int,
  next_step_at     timestamptz,
  snapshot         jsonb not null default '{}',  -- name, start, destination, last location, reasons
  acknowledged_by  uuid references public.contacts(id) on delete set null,
  opened_at        timestamptz not null default now(),
  closed_at        timestamptz
);
create index if not exists escalations_open_idx on public.escalations (status, next_step_at);

-- Every email sent (or attempted). Unique key prevents duplicates within an episode.
create table if not exists public.notifications_sent (
  id               uuid primary key default gen_random_uuid(),
  escalation_id    uuid references public.escalations(id) on delete cascade,
  journey_id       text not null,
  recipient        text not null,
  kind             text not null,
  ack_token_hash   text,
  gmail_message_id text,
  error            text,
  sent_at          timestamptz not null default now(),
  unique (escalation_id, kind, recipient)
);

alter table public.google_accounts    enable row level security;
alter table public.contacts           enable row level security;
alter table public.escalations        enable row level security;
alter table public.notifications_sent enable row level security;

-- Private bucket for contact photos (backend hands out signed URLs).
insert into storage.buckets (id, name, public)
values ('contact-photos', 'contact-photos', false)
on conflict (id) do nothing;
