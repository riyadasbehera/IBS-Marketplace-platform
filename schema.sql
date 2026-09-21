
-- IBS Marketplace
-- Run this once in Supabase SQL Editor.
-- The Streamlit app uses the Supabase server-side secret key, so the app
-- performs authorization checks before every user-facing operation.

create extension if not exists pgcrypto;

create table if not exists public.profiles (
    id uuid primary key default gen_random_uuid(),
    google_sub text unique not null,
    email text unique not null,
    display_name text not null,
    avatar_url text,
    created_at timestamptz not null default now()
);

create table if not exists public.listings (
    id uuid primary key default gen_random_uuid(),
    seller_id uuid not null references public.profiles(id) on delete cascade,
    title text not null,
    category text not null,
    listing_type text not null,
    condition text not null,
    age_months integer not null default 0,
    original_price numeric(12,2) not null default 0,
    price numeric(12,2) not null default 0,
    price_floor numeric(12,2) not null default 0,
    meetup_zone text not null,
    tags text,
    description text not null,
    image_data text,
    image_hash text,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists listings_status_idx on public.listings(status);
create index if not exists listings_category_idx on public.listings(category);
create index if not exists listings_meetup_zone_idx on public.listings(meetup_zone);
create index if not exists listings_seller_idx on public.listings(seller_id);

create table if not exists public.watchlists (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    listing_id uuid not null references public.listings(id) on delete cascade,
    created_at timestamptz not null default now(),
    unique(user_id, listing_id)
);

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    listing_id uuid not null references public.listings(id) on delete cascade,
    buyer_id uuid not null references public.profiles(id) on delete cascade,
    seller_id uuid not null references public.profiles(id) on delete cascade,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(listing_id, buyer_id, seller_id)
);

create index if not exists conversations_buyer_idx on public.conversations(buyer_id);
create index if not exists conversations_seller_idx on public.conversations(seller_id);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    sender_id uuid not null references public.profiles(id) on delete cascade,
    body text not null,
    created_at timestamptz not null default now()
);

create index if not exists messages_conversation_idx
on public.messages(conversation_id, created_at);

create table if not exists public.transactions (
    id uuid primary key default gen_random_uuid(),
    listing_id uuid not null references public.listings(id) on delete cascade,
    buyer_id uuid not null references public.profiles(id) on delete restrict,
    seller_id uuid not null references public.profiles(id) on delete restrict,
    category text not null,
    item_condition text not null,
    original_price numeric(12,2) not null default 0,
    listing_price numeric(12,2) not null default 0,
    sale_price numeric(12,2) not null default 0,
    status text not null default 'completed',
    completed_at timestamptz not null default now(),
    unique(listing_id)
);

create index if not exists transactions_category_idx
on public.transactions(category, completed_at);

create table if not exists public.ratings (
    id uuid primary key default gen_random_uuid(),
    transaction_id uuid not null references public.transactions(id) on delete cascade,
    from_user_id uuid not null references public.profiles(id) on delete cascade,
    to_user_id uuid not null references public.profiles(id) on delete cascade,
    score integer not null check (score between 1 and 5),
    comment text,
    created_at timestamptz not null default now(),
    unique(transaction_id, from_user_id)
);

create index if not exists ratings_to_user_idx on public.ratings(to_user_id);

-- Recommended production hardening:
-- 1) Keep the Supabase server-side secret key ONLY in Streamlit secrets.
-- 2) Do not put that key into GitHub.
-- 3) For a production build, replace broad service-key access with
--    Supabase Auth/JWT + RLS or move sensitive operations to Edge Functions.
