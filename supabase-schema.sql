-- APITOU — esquema do paywall (colar em Supabase → SQL Editor → Run)
-- Perfil de cada usuário: WhatsApp (lead!), início do trial e status premium.

create table if not exists public.perfis (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  whatsapp text not null,
  criado_em timestamptz not null default now(),
  trial_inicio timestamptz not null default now(),
  premium boolean not null default false,
  premium_ate timestamptz,                -- preenchido pelo RevenueCat/Stripe depois
  origem text default 'web'
);

alter table public.perfis enable row level security;

-- cada usuário lê e cria só o próprio perfil; NINGUÉM edita premium pelo cliente
create policy "ler o próprio perfil" on public.perfis
  for select using (auth.uid() = id);
create policy "criar o próprio perfil" on public.perfis
  for insert with check (auth.uid() = id);

-- visão administrativa dos leads (WhatsApp) — só via service key / painel
-- (nenhuma policy de select público: a lista de leads nunca vaza pro cliente)

-- função de status: o CLIENTE pergunta, o SERVIDOR responde (não dá pra burlar
-- reinstalando/limpando o navegador — o relógio do trial mora aqui)
create or replace function public.meu_acesso()
returns json language sql security definer set search_path = public as $$
  select json_build_object(
    'premium', coalesce(p.premium and (p.premium_ate is null or p.premium_ate > now()), false),
    'trial_fim', p.trial_inicio + interval '3 days',
    'trial_ativo', now() < p.trial_inicio + interval '3 days'
  )
  from public.perfis p where p.id = auth.uid();
$$;
