# SOLUTION

> Completează acest fișier. Răspunsurile scurte și concrete sunt preferate.

## 1. Probleme identificate și cum le-ai rezolvat

Pentru fiecare problemă: simptom → cum ai investigat (comenzi, loguri, ipoteze) → cauză → soluție.

| # | Componentă | Simptom | Cauză | Soluție |
|---|------------|---------|-------|---------|
| 1 | worker           | Crash la start: psycopg.OperationalError: connection failed: ... "172.20.0.2", port 5432 failed, si programul se opreste       |  Race condition la boot, workerul incearca sa se conecteze inainte ca DB sa fie ready (depends_on doar asigura ca DB a pornit, nu ca postgress este pornit complet)     |  Retry cu conectare în worker.py si depends_on: condition: service_healthy       |
| 2 | FastAPI/gateway           | nginx returneaza 502 Bad Gateway la GET http://localhost:8080/health        |   Uvicorn pornit pe 127.0.0.1:8000 în api/Dockerfile, asculta doar in propriul container    | modificat  127.0.0.1 in 0.0.0.0 in   api/Dockerfile     |
| 3 | worker | Containerele worker nu afiseaza nimic in log-uri pana se inchid. | Print e buffered by default, bufferul isi ia flush fie prin print cu flush=True sau la inchidere | Adaugarea -u la comanda python in worker/Dockerfile pentru a folosi modul unbuffered | 

## 2. Diagnostic networking

sudo docker-compose up --build -d
sudo docker-compose logs --tail=50 -> am vazut ca workeri nu se pot conecta la DB, si ca DB raporteaza "database system is ready to accept connections" mult dupa workeri. 
sudo docker-compose exec api python -c "import socket; socket.create_connection(('db',5432),3); print('ok')" -> confirmare ca problema de conectare la DB este un race condition (api e in network-ul backend, containerele de workeri s-au oprit dupa esecul de conectare)

curl -i http://localhost:8080/health > nginx raspunde dar returneaza 502 Bad Gateway, in general semnificand o problema la ce e in spatele nginx.
sudo docker-compose logs | grep api -> api-1  | INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit) arata ca Uvicorn asculta doar localhost.


## 3. Decizii tehnice

- Idempotency:
- Retry (ce erori consideri temporare, backoff):
- Recuperare după restart:
- Altele:

## 4. Cum pornești și verifici sistemul

```bash
# comenzi
```

## 5. Instrumente AI utilizate

Ce instrumente ai folosit, pentru ce, și cum ai verificat ce au produs.
Menționează cel puțin un caz în care AI-ul a greșit și cum ai observat.

## 6. Ce ai îmbunătăți cu mai mult timp
Folosirea psycopg_pool in loc de o singura conexiune intr-un loop penru retry.
