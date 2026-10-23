# Integracija u Moodle -- uputstvo

Ovaj dio demonstrira PRAKTIČNU primjenjivost implementiranih agenata kroz
povezivanje s Moodle-ovim ugrađenim AI Subsystem-om (dostupnim od
Moodle 4.5 nadalje). Namjerno je odvojen od eksperimentalnog dijela
rada (`run_full_simulation.py`), koji ostaje glavni izvor podataka za
poglavlje 5 -- ovo je dodatna, praktična demonstracija.

## Arhitektura

```
Moodle (AI chat sučelje, ugrađeno)
    |
    v
aiprovider_elttutor  (PHP plugin -- moodle_plugin/)
    |  HTTP POST /generate
    v
moodle_api.py (FastAPI servis -- api/)
    |
    v
common/llm_client.py -> Groq -> jezički model
```

Provider plugin je namjerno "tanak" -- ne sadrži pedagošku logiku, samo
prosljeđuje Moodle-ov upit prema FastAPI servisu i vraća odgovor.
Napomena: ova verzija koristi direktan poziv modela (isti sistemski
prompt za sve upite), NE punu adaptivnu petlju s praćenjem mastery-ja
i biranjem sljedećeg zadatka -- to bi zahtijevalo dodatan Moodle
"activity module" plugin (npr. po uzoru na mod_maici) koji bi čuvao
stanje sesije po studentu, što nadilazi obim ove demonstracije.

## Koraci postavljanja

### 1. Pokreni FastAPI servis

Iz korijena projekta (uz već pokrenutu bazu/Groq ključ):
```bash
pip install fastapi uvicorn
uvicorn moodle_integration.api.moodle_api:app --host 0.0.0.0 --port 8100
```

Provjeri: `curl http://localhost:8100/health`

### 2. Instaliraj Moodle plugin

Ako imaš lokalnu Moodle instalaciju (npr. za potrebe demonstracije na
odbrani), kopiraj cijeli `moodle_plugin/` folder u:
```
<moodle_root>/ai/provider/elttutor/
```

Zatim, kao admin, idi na:
```
Site administration > Notifications
```
Moodle će prepoznati novi plugin i ponuditi instalaciju.

### 3. Konfiguriši i uključi provider

```
Site administration > Plugins > AI > AI providers > ELT Tutor (diplomski rad)
```
Unesi adresu FastAPI servisa (npr. `http://localhost:8100` ako je Moodle
na istom serveru, ili tačnu mrežnu adresu ako je odvojeno).

### 4. Poveži s placement-om

```
Site administration > Plugins > AI > AI placements
```
Uključi "Course Assistant" (ili drugi placement) i odaberi
`aiprovider_elttutor` kao provider za akciju generisanja teksta.

## Ograničenja ove demonstracije (za poglavlje 6/7 rada)

- Radi se o pojednostavljenom, "upitno-odgovornom" modu -- ne replicira
  punu adaptivnu petlju (izbor sljedećeg zadatka, mastery praćenje)
  koja postoji u `run_full_simulation.py`.
- Koristi samo LangGraph implementaciju (najbolji rezultat u eksperimentu,
  poglavlje 5) -- lako zamjenjivo s bilo kojom od preostale 3, budući da
  sve dijele isti `common/contract.py` ugovor.
- Za punu adaptivnu funkcionalnost unutar Moodle-a, sljedeći korak bio bi
  Moodle "activity module" plugin (ne samo provider) koji bi čuvao stanje
  sesije po studentu -- ovo je prijedlog za budući rad, ne dio trenutne
  implementacije.
