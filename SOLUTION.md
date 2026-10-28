# SOLUTION

> Completează acest fișier. Răspunsurile scurte și concrete sunt preferate.

## 1. Probleme identificate și cum le-ai rezolvat

Pentru fiecare problemă: simptom → cum ai investigat (comenzi, loguri, ipoteze) → cauză → soluție.

| # | Componentă | Simptom | Cauză | Soluție |
|---|------------|---------|-------|---------|
| 1 | worker | Crash la start: 'psycopg.OperationalError: connection failed: ... "172.20.0.2", port 5432 failed', si programul se opreste | Race condition la boot, workerul incearca sa se conecteze inainte ca DB sa fie ready (depends_on doar asigura ca DB a pornit, nu ca postgres este pornit complet) | Retry cu conectare în worker.py (connect_with_retry) si depends_on: condition: service_healthy |
| 2 | FastAPI | nginx returneaza 502 Bad Gateway la GET http://localhost:8080/health | Uvicorn pornit pe 127.0.0.1:8000 în api/Dockerfile, asculta doar in propriul container | modificat 127.0.0.1 in 0.0.0.0 in api/Dockerfile |
| 3 | worker | Containerele worker nu afiseaza nimic in log-uri ('docker compose logs worker' gol) pana se inchid. | Print e buffered by default, bufferul isi ia flush fie prin print cu flush=True sau la inchidere | Adaugarea -u la comanda python in worker/Dockerfile pentru a folosi modul unbuffered |
| 4 | nginx | POST cu un nou event returneaza 422 Unprocessable Entity cu '{"detail":[{"type":"missing","loc":["body"],"msg":"Field required","input":null}]}' | Nginx are 'proxy_pass_request_body off' pentru /events si sterge body-ul. | Eliminarea linilor 'proxy_pass_request_body off' si 'proxy_set_header Content-Length ""' |
| 5 | worker/receiver | Status failed la eveniment nou dupa 3 incercari | gethostbyname('receiver') returneaza 192.0.2.10, ip gresit din cauza docker-compose.override.yml | stergerea docker-compose.override.yml |
| 6 | DB | DB accesibil din host la localhost:5432 | docker-compose.override.yml configura 'ports: - "127.0.0.1::5432"' | stergerea docker-compose.override.yml |
| 7 | worker/receiver | Receiver-ul a raspuns 401 la evenimentul trimis de worker | 'raw = json.dumps(body).encode()' are spatii albe care intra in token, in timp ce receiverul primeste json fara spati albe -> creaza alt token | Inlocuirea serializari implicite httpx cu una explicita folosind 'json.dumps().encode()', noua implemetare respecta si cerinta din contract despre HMAC peste body-ul brut |
| 8 | worker | Eveniment care a primit 401 de la receiver a fost marcat delivered | 'deliver()' returna 'attempt' indiferent de raspunsul HTTP | modificat functia 'deliver()' astfel incat sa returnze si daca procesarea a fost cu success si modificat 'main' pentru noul return |
| 9 | worker | Ambii workeri pot captura acelasi eveniment pending | 'fetch_pending' fara ownership, ambii workerii vad pending in DB si incep sa proceseze acelasi eveniment | claim pe eveniment inainte de procesare, postgres asigura atomicitatea operatiei UPDATE facuta de unul din cei 2 workeri |
| 10 | worker | Nu se respeca Retry-After | Retry-After nu este verificat in 'worker.py' | Aduagarea verificari headerului Retry-After, valoarea acestuia find folosita ca minim pentru retry |
| 11 | worker | Workerul nu avea handle pentru semnale | Fara handler: SIGTERM termina procesul cu comportamentul implicit (brusc), procesarea curenta ramane blocata in "processing" | am adaugat handler SIGTERM/SIGINT: termina procesarea curenta si se opreste |
| 12 | worker | Workerul nu primea semnalele de la docker | Dockerfile avea 'CMD python -u worker.py' ceea ce se rezolva la '/bin/sh -c python -u worker.py' -> python nu avea PID 1 si nu primea semnalele | Am inlocuit 'CMD python -u worker.py' cu 'CMD exec python -u worker.py' |
| 13 | worker | Evenimentele ramase in DB cu "processing" nu erau recuperate | worker nu verifica existenta acestui tip de eveniment | Am implementat un recovery la pornire a acestor evenimente (recover_stale) |
| 14 | api | POST /events cu aceeasi event_id (acelasi/diferit continut) returna mereu 202 | Nu exista constraint UNIQUE pe event_id si nici logica de idempotency in create_event | Migratie db/002 (UNIQUE pe event_id) + create_event: id existent cu continut identic returneaza 200 cu starea curenta (fara re-procesare), continut diferit returneaza 409; race pe INSERT simultan catch UniqueViolation duce la rollback si re-check |
| 15 | api/worker | GET /events/{id} nu expunea istoricul incercarilor | deliver() nu scria nimic in delivery_attempts | record_attempt() in worker si GET /events/{id} citeste delivery_attempts din DB |
| 16 | api | GET /metrics nu era implementat | - | /metrics implementat ca Response(content=..., media_type="text/plain") cu linii HELP/TYPE si contoare din DB (status per eveniment + attempts_total) |
| 17 | nginx | Payload de ~1 MB respins cu 413 | client_max_body_size 1k | client_max_body_size 2m; |
| 18 | nginx | Response-urile nu aveau headerul X-Request-ID | lipsa propagarii request-id | map $http_x_request_id (ID-ul de la client, fallback $request_id), propagat cu proxy_set_header si returnat cu add_header ... always; |
| 18 | compose | Credentialele DB si WEBHOOK_SECRET era hardcodate in docker-compose.yml | - | Blocuri environment cu ${VAR} + .env (in .gitignore) + .env.example |
| 19 | CI | .github/workflows/ci.yml era placeholder (TODO) | - | Pipeline: unit tests (fara stack), docker compose up --build, asteptare pentru /health, pytest tests |

## 2. Diagnostic networking

sudo docker-compose up --build -d

sudo docker-compose logs --tail=50 -> am vazut ca workeri nu se pot conecta la DB, si ca DB raporteaza "database system is ready to accept connections" mult dupa workeri.

sudo docker-compose exec api python -c "import socket; socket.create_connection(('db',5432),3); print('ok')" -> confirmare ca problema de conectare la DB este un race condition (api e in network-ul backend, containerele de workeri s-au oprit dupa esecul de conectare)

sudo docker-compose exec worker python -c "import socket; print(socket.gethostbyname('receiver'))" -> verificare DNS intre containere -> 192.0.2.10 -> docker-compose.override.yml cu extra_hosts

curl -i http://localhost:8080/health > nginx raspunde dar returneaza 502 Bad Gateway, in general semnificand o problema la ce e in spatele nginx.

sudo docker-compose logs | grep api -> api-1  | INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit) arata ca Uvicorn asculta doar localhost.

curl -s -i -X POST http://localhost:8080/events -d @/tmp/big.json -> 413 -> nginx.conf avea client_max_body_size 1k; curl -i /health -> X-Request-ID lipsea din response -> adaugat map + add_header ... always.

## 3. Decizii tehnice

- Idempotency: Daca la POST exista deja un eveniment cu acelasi id se compara body-ul si type-ul si daca sunt egale se returneza 200 (starea curenta, fara re-procesare), altfel 409. Daca nu exista conflict de id atunci se adauga noul eveniment si se returneaza 202. Peste asta sta constraint-ul UNIQUE ca ultima protectie: la doua POST-uri simultane pe acelasi id se genereaza UniqueViolation care duce la rollback + re-check si returneaza 200 sau 409, niciodata duplicate.
- Retry (ce erori consideri temporare, backoff): Erori temporare sunt considerate erorile de retea (timeout 5s sau conexiune refuzata), 429, 5xx. Backoff-ul este 2^attempt (2s, 4s, 8s) cu Retry-After ca minim (delay = max(2**attempt, Retry-After)). Se fac maxim 3 incercari, dupa care se marcheaza failed. Erori permanete sunt orice alt cod (400, 401) marcare failed, fara retry.
- Recuperare după restart: La start workerul ia toate evenimetele cu status "processing" si le modifica status-ul la "pending" (claim-ul este invalidat). Delivered/failed raman la fel.
- Altele: atomicitatea o da postgres, nu aplicatia; SIGTERM duce la terminarea livrarii curente si se termina in cateva secunde, fara evenimente blocate. Healthcheck pe toate serviciile (db/api/receiver/gateway) mai putin worker.


## 4. Cum pornești și verifici sistemul

In functie de distributie sintaxa pentru docker compose poate sa difere:
```bash
sudo docker-compose up -d --build
```
sau
```bash
sudo docker compose up -d --build
```

Flow complet de pornire si verificare:
```bash
cp .env.example .env
sudo docker-compose up -d --build
sudo docker-compose ps # asigurare ca db/api/receiver/gateway au status healthy
curl -s -i http://localhost:8080/health
curl -s -X POST http://localhost:8080/events -H 'Content-Type: application/json' -d '{"event_id":"event1","type":"t","payload":{"x":1}}'
curl -s http://localhost:8080/events/event1
curl -s http://localhost:9000/received
curl -s http://localhost:8080/metrics
pip install -r tests/requirements.txt
pytest tests
sudo docker-compose down
```

## 5. Instrumente AI utilizate

Am utilizat Swift-Qwen3.8-27B (fine tune de Qwen3.8 27B pentru mai putin overthinking) hostat local prin Hermes Agent. Agentul a fost folosit doar ca ghid si pentru cod, rularea efectiva a comenzilor si implemnetarea solutilor oferite de acesta au fost facute manual pentru validare.

Doua cazuri in care AI-ul a gresit: 
    - a considerat ca SIGTERM nu era handled si caut bug-uri in handler. Problema fiind default faptul ca procesul python nu avea PID 1 in container si nu primea semnalele. 
    - a implementat functia de idempotency fara sa ia in calcul returnul diferite 200/202 pentru eveniment nou sau existent.

## 6. Ce ai îmbunătăți cu mai mult timp
Folosirea psycopg_pool in loc de o singura conexiune intr-un loop pentru retry. 
Teste pentru oprirea brusca a worker-ului (kill worker in timpul unei livrari) pentru a verifica recuperarea si absenta duplicatelor).

