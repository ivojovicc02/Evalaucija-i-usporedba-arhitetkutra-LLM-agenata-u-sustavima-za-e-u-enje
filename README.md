# Usporedba arhitektura LLM agenata u sustavima za e-učenje

Projekt uspoređuje četiri okvira za izgradnju LLM agenata (LangGraph,
LlamaIndex Workflows, CrewAI, OpenAI Agents SDK) na istom zadatku u
e-učenju: dijagnoza pogreške u studentskom kodu i odabir sljedećeg
pedagoškog koraka.

Jezični model: `openai/gpt-oss-20b` preko Groq API-ja.

## Struktura projekta

| Mapa / datoteka | Sadržaj |
|---|---|
| `common/` | Zajednički dio: ugovor (`contract.py`), LLM klijent (`llm_client.py`), pedagoška politika (`policy.py`), pristup zadacima (`task_repo.py`) |
| `frameworks/` | Po jedna implementacija agenta za svaki okvir: `langgraph/`, `llamaindex/`, `crewai/`, `openai_sdk/` |
| `simulator/` | Simulator studenata (`student_simulator.py`) |
| `db/` | PostgreSQL shema, početni podaci i učitavanje zadataka |
| `tasks/` | Definicije zadataka u JSON formatu (tekst, testovi, tipične pogreške) |
| `results/` | CSV datoteke s mjerenjima i agregirani sažetak |
| `moodle_integration/` | Integracija s Moodleom |
| `run_full_simulation.py` | Glavna skripta za prikupljanje podataka |
| `aggregate_results.py` | Agregacija izmjerenih rezultata |

## Preduvjeti

- Python 3.12 ili noviji
- PostgreSQL
- Servis za izvršavanje studentskog koda (sandbox) dostupan na
  `http://localhost:8090` (varijabla `ELT_SANDBOX_URL`)
- Groq API ključ

Biblioteke koje projekt koristi: `psycopg2-binary`, `requests`,
`langgraph`, `llama-index`, `crewai`, `openai-agents`.

## Postavljanje

1. Postavi varijable okoline. Ključ nikada ne spremaj u datoteku unutar
   projekta.

   Windows:
   ```
   setx GROQ_API_KEY "tvoj_kljuc"
   ```
   Nakon toga otvori novi terminal.

2. Napravi bazu `elt_agents` i učitaj podatke, ovim redom:
   ```
   psql -U elt_admin -d elt_agents -f db/schema.sql
   psql -U elt_admin -d elt_agents -f db/seed_base.sql
   python db/load_tasks.py
   ```
   - `schema.sql` stvara tablice.
   - `seed_base.sql` unosi 4 koncepta (`if_else`, `for_loop`, `while_loop`,
     `nested`) i 3 profila studenata.
   - `load_tasks.py` učitava zadatke iz mape `tasks/`. Preskače zadatke
     koji već postoje, pa se može pokrenuti ponovno.

## Varijable okoline

| Varijabla | Zadano | Značenje |
|---|---|---|
| `GROQ_API_KEY` | obavezno | Groq API ključ |
| `ELT_AGENT_MODEL` | zadani model u `agent.py` datoteci okvira | Model koji koriste agenti |
| `ELT_SIMULATOR_MODEL` | `openai/gpt-oss-20b` | Model simulatora studenata |
| `ELT_SANDBOX_URL` | `http://localhost:8090` | Servis za izvršavanje koda |
| `ELT_DB_HOST` | `localhost` | Baza |
| `ELT_DB_PORT` | `5432` | Baza |
| `ELT_DB_NAME` | `elt_agents` | Baza |
| `ELT_DB_USER` | `elt_admin` | Baza |
| `ELT_DB_PASSWORD` | `change_me_locally` | Zadana lozinka je samo za lokalni razvoj; promijeni je |

Za reproduciranje mjerenja postavi `ELT_AGENT_MODEL=openai/gpt-oss-20b`.

## Pokretanje

Iz korijena projekta:

```
py run_full_simulation.py --seed 42
```

Skripta pokreće 4 okvira x 3 profila studenata, svaki kroz punu sesiju
(od prvog zadatka do `COMPLETE` ili sigurnosnog limita koraka). Svaka
interakcija se zapisuje u tablicu `interaction_logs`.

| Argument | Značenje |
|---|---|
| `--seed` | Seed simulatora, isti za sve okvire |
| `--frameworks` | Zarezom odvojen popis okvira, npr. `langgraph,crewai` |
| `--profiles` | Zarezom odvojen popis profila, npr. `common_errors` |

Primjer ograničenog pokretanja:

```
py run_full_simulation.py --seed 42 --frameworks langgraph,crewai --profiles common_errors
```

Agregacija rezultata:

```
py aggregate_results.py
```

Samostalni test simulatora (bez agenta):

```
py simulator/student_simulator.py --profile common_errors --task-title "Predznak broja" --seed 42
```

## Profili studenata

- `fast_accurate`: brz i točan student, ne pravi tipične pogreške
- `common_errors`: student s tipičnim pogreškama iz definicije zadatka
- `slow_unsure`: spor i nesiguran student, povremeno postavlja kratka i
  nejasna pitanja umjesto koda

Ponašanje svakog profila definirano je poljem `behavior_spec` (JSONB) u
tablici `student_profiles`.

## Determinizam simulatora

RNG simulatora seedira se kombinacijom seeda, zadatka i broja pokušaja.
Isti `--seed` daje identičan odabir tipa pokušaja (točan, pogrešan,
pojašnjenje) i pogreške za isti zadatak i pokušaj kroz sva 4 okvira.
Razlike u ishodu proizlaze iz orkestracije i odgovora jezičnog modela, a
ne iz različitog scenarija studenta.

Tekst koda koji generira LLM i dalje varira između pokretanja, jer simulator
koristi temperaturu 0,2 (točni pokušaji) i 0,7 (pogrešni pokušaji i
pojašnjenja).

## Što se mjeri

Latencija, broj LLM poziva, ulazni i izlazni tokeni te točnost rješenja i
dijagnoze, po okviru.

## Ograničenja

- Jedan seed i jedan model.
- CrewAI i OpenAI Agents SDK ne postavljaju eksplicitno temperaturu ni
  izlaznu granicu tokena te koriste vlastite klijente.
- Mjerenja za LangGraph i LlamaIndex nisu provedena istog dana kao
  mjerenja za CrewAI i OpenAI Agents SDK.
- Model je reasoning model, pa skriveni tokeni razmišljanja troše izlaznu
  granicu (`max_tokens`) i mogu skratiti odgovor.
