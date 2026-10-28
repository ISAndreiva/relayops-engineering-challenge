# SOLUTION

> Completează acest fișier. Răspunsurile scurte și concrete sunt preferate.

## 1. Probleme identificate și cum le-ai rezolvat

Pentru fiecare problemă: simptom → cum ai investigat (comenzi, loguri, ipoteze) → cauză → soluție.

| # | Componentă | Simptom | Cauză | Soluție |
|---|------------|---------|-------|---------|
| 1 | worker           | Crash la start: 'psycopg.OperationalError: connection failed: ... "172.20.0.2", port 5432 failed', si programul se opreste       |  Race condition la boot, workerul incearca sa se conecteze inainte ca DB sa fie ready (depends_on doar asigura ca DB a pornit, nu ca postgress este pornit complet)     |  Retry cu conectare în worker.py si depends_on: condition: service_healthy       |
| 2 | FastAPI           | nginx returneaza 502 Bad Gateway la GET http://localhost:8080/health        |   Uvicorn pornit pe 127.0.0.1:8000 în api/Dockerfile, asculta doar in propriul container    | modificat  127.0.0.1 in 0.0.0.0 in   api/Dockerfile     |
| 3 | worker | Containerele worker nu afiseaza nimic in log-uri ('docker compose logs worker' gol) pana se inchid. | Print e buffered by default, bufferul isi ia flush fie prin print cu flush=True sau la inchidere | Adaugarea -u la comanda python in worker/Dockerfile pentru a folosi modul unbuffered | 
| 4 | nginx | POST cu un nou event returneaza 422 Unprocessable Entity cu '{"detail":[{"type":"missing","loc":["body"],"msg":"Field required","input":null}]}' | Nginx are 'proxy_pass_request_body off' pentru /events si sterge body-ul. | Eliminarea linilor 'proxy_pass_request_body off' si 'proxy_set_header Content-Length ""'  |
| 5 | worker/receiver | status failed la eveniment nou dupa 3 incercari | gethostbyname('receiver') returneaza 192.0.2.10, ip gresit din cauza docker-compose.override.yml | stergerea docker-compose.override.yml |
| 6 | DB | db accesibil din host la localhost:5432 | docker-compose.override.yml configura 'ports: - "127.0.0.1::5432"' | stergerea docker-compose.override.yml |
| 7 | worker/receiver | Receiver-ul a raspuns 401 la evenimentul trimis de worker | 'raw = json.dumps(body).encode()' are spatii albe care intra in token, in timp ce receiverul primeste json fara spati albe -> creaza alt token | Inlocuirea serializari implicite httpx cu una explicita folosind 'json.dumps().encode()', noua implemetare respecta si cerinta din contract despre HMAC peste body-ul brut |
| 8 | worker | Eveniment care a primit 401 de la receiver a fost marcat delivered | 'deliver()' returna 'attempt' indiferent de raspunsul HTTP | modificat functia 'deliver()' astfel incat sa returnze si daca livrarea a fost cu success si modificat 'main' pentru noul return |
| 9 | worker | Ambii workeri pot captura acelasi eveniment pending | 'fetch_pending' fara ownership, ambii workerii vad pending in DB si incep sa proceseze acelasi eveniment | claim pe eveniment inainte de procesare, postgres asigura atomicitatea operatiei UPDATE facuta de unul din cei 2 workeri |
| 10 | worker | nu se respeca Retry-After | Retry-After nu este verificat in 'worker.py' | Aduagarea verificari headerului Retry-After, valoarea acestuia find folosita ca minim pentru retry |
| 11 | worker | workerul nu avea handle pentru semnale | - | am adaugat handler |
| 12 | worker | workerul nu primea semnalele de la docker | Dockerfile avea 'CMD python -u worker.py' ceea ce se rezolva la '/bin/sh -c python -u worker.py' -> python nu avea PID 1 si nu primea semnalele | Am inlocuit 'CMD python -u worker.py' cu 'CMD exec python -u worker.py' |
| 13 | worker | evenimentele ramase in DB cu "processing" nu erau recuperate | worker nu verifica existenta acestui tip de eveniment | Am implementat un recovery la pornire a acestor evenimente 

## 2. Diagnostic networking

sudo docker-compose up --build -d
sudo docker-compose logs --tail=50 -> am vazut ca workeri nu se pot conecta la DB, si ca DB raporteaza "database system is ready to accept connections" mult dupa workeri. 
sudo docker-compose exec api python -c "import socket; socket.create_connection(('db',5432),3); print('ok')" -> confirmare ca problema de conectare la DB este un race condition (api e in network-ul backend, containerele de workeri s-au oprit dupa esecul de conectare)

sudo docker-compose exec worker python -c "import socket; print(socket.gethostbyname('receiver'))" -> verificare DNS intre containere

curl -i http://localhost:8080/health > nginx raspunde dar returneaza 502 Bad Gateway, in general semnificand o problema la ce e in spatele nginx.
sudo docker-compose logs | grep api -> api-1  | INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit) arata ca Uvicorn asculta doar localhost.


## 3. Decizii tehnice

- Idempotency: Daca la POST exista deja un eveniment cu acelasi id se compara body-ul si type-ul si daca sunt egale se returneza 200, altfel 409. Daca nu exista conflict de id atunci se adauga noul eveniment si se returneaza 202. 
- Retry (ce erori consideri temporare, backoff): Erorile de retea sunt cele considerate temporare (429, 5xx), backoff-ul se face crescand timpul dintre retry-uri cu puteri ale lui 2.
- Recuperare după restart: La start workerul ia toate evenimetele cu status "processing" si le modifica status-ul la "pending".
- Altele:

## 4. Cum pornești și verifici sistemul

In functie de distributie sintaxa pentru docker compose poate sa difere:
```bash
sudo docker-compose up -d --build
sudo docker-compose logs
```
sau
```bash
sudo docker compose up -d --build
sudo docker compose logs
```
In rest comenzile de test:
```bash
curl -s -i http://localhost:8080/health
curl -s -X POST http://localhost:8080/events -H 'Content-Type: application/json' -d '{"event_id":"event1","type":"t","payload":{"x":1}}'
...
curl -s http://localhost:8080/metrics
```

## 5. Instrumente AI utilizate

Am utilizat Swift-Qwen3.8-27B (fine tune de Qwen3.8 27B pentru mai putin overthinking) hostat local si Hermes Agent. Agentul a fost folosit doar ca ghid si pentru cod, rularea efectiva a comenzilor si implemnetarea solutilor oferite de acesta au fost facute manual pentru validare.

## 6. Ce ai îmbunătăți cu mai mult timp
Folosirea psycopg_pool in loc de o singura conexiune intr-un loop pentru retry.
