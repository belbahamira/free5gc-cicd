# Makefile — CI/CD Free5GC autoscaling scenarios
SCRIPTS    := scripts
RESULTS    := results
DURATION   := 180
INTERVAL   := 5
PROMETHEUS := http://localhost:9090
NS         := free5gc

.PHONY: all setup port-forward check-prometheus stop-traffic reset-ues
.PHONY: scenario-4ues scenario-10ues scenario-20ues all-scenarios compare clean help

all: setup scenario-4ues

setup:
	@mkdir -p $(RESULTS)
	@echo "[OK] Dossier $(RESULTS)/ pret"

check-prometheus:
	@curl -sf $(PROMETHEUS)/-/healthy > /dev/null || (echo "[ERREUR] Prometheus inaccessible. Lance: make port-forward" && exit 1)
	@echo "[OK] Prometheus accessible"

port-forward:
	pkill -f "port-forward.*9090" 2>/dev/null || true
	kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090 &
	sleep 3
	@echo "[OK] Prometheus sur $(PROMETHEUS)"

stop-traffic:
	python3 $(SCRIPTS)/traffic-gen.py --stop

reset-ues:
	python3 $(SCRIPTS)/deploy-ues.py --delete --start 6 --count 20 2>/dev/null || true
	@echo "[OK] UEs 006+ supprimes"

scenario-4ues: setup check-prometheus
	@echo "=== SCENARIO 1 : 4 UEs ==="
	@echo "[INFO] Attente UPF Running..."
	kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=upf -n free5gc --timeout=180s 2>/dev/null || true
	python3 $(SCRIPTS)/traffic-gen.py --ues 4 --duration $(DURATION) --pps 200 --size 1400 &
	python3 $(SCRIPTS)/metrics-collector.py --scenario 4ues --duration $(DURATION) --interval $(INTERVAL) --output $(RESULTS)/scenario-4ues.csv --prometheus $(PROMETHEUS)
	@wait
	@echo "[FIN] $(RESULTS)/scenario-4ues.csv"

scenario-10ues: setup check-prometheus
	@echo "=== SCENARIO 2 : 10 UEs ==="
	@echo "[INFO] Provisionnement abonnes MongoDB (UE-006 -> UE-011)..."
	python3 $(SCRIPTS)/provision-ues.py --start 6 --count 6
	python3 $(SCRIPTS)/deploy-ues.py --count 6 --start 6 --timeout 180
	@echo "[INFO] Attente etablissement PDU sessions (45s)..."
	sleep 45
	python3 $(SCRIPTS)/traffic-gen.py --ues 10 --duration $(DURATION) --pps 200 --size 1400 &
	python3 $(SCRIPTS)/metrics-collector.py --scenario 10ues --duration $(DURATION) --interval $(INTERVAL) --output $(RESULTS)/scenario-10ues.csv --prometheus $(PROMETHEUS)
	@wait
	python3 $(SCRIPTS)/deploy-ues.py --delete --start 6 --count 6
	@echo "[FIN] $(RESULTS)/scenario-10ues.csv"

scenario-20ues: setup check-prometheus
	@echo "=== SCENARIO 3 : 20 UEs ==="
	@echo "[INFO] Provisionnement abonnes MongoDB (UE-006 -> UE-021)..."
	python3 $(SCRIPTS)/provision-ues.py --start 6 --count 16
	python3 $(SCRIPTS)/deploy-ues.py --count 16 --start 6 --timeout 300
	@echo "[INFO] Attente etablissement PDU sessions (120s)..."
	sleep 120
	python3 $(SCRIPTS)/traffic-gen.py --ues 20 --duration 300 --pps 200 --size 1400 &
	python3 $(SCRIPTS)/metrics-collector.py --scenario 20ues --duration 300 --interval $(INTERVAL) --output $(RESULTS)/scenario-20ues.csv --prometheus $(PROMETHEUS) &
	@echo "[INFO] Scale-down progressif..."
	sleep 60
	@echo "[INFO] Suppression 4 UEs (018-021)..."
	python3 $(SCRIPTS)/deploy-ues.py --delete --start 18 --count 4
	sleep 45
	@echo "[INFO] Suppression 4 UEs (014-017)..."
	python3 $(SCRIPTS)/deploy-ues.py --delete --start 14 --count 4
	sleep 45
	@echo "[INFO] Suppression 4 UEs (010-013)..."
	python3 $(SCRIPTS)/deploy-ues.py --delete --start 10 --count 4
	sleep 45
	@echo "[INFO] Suppression 4 UEs (006-009)..."
	python3 $(SCRIPTS)/deploy-ues.py --delete --start 6 --count 4
	@wait
	@echo "[FIN] $(RESULTS)/scenario-20ues.csv"

all-scenarios: scenario-4ues scenario-10ues scenario-20ues compare

compare:
	python3 $(SCRIPTS)/compare-results.py $(RESULTS)

clean:
	rm -f $(RESULTS)/*.csv
	@echo "[OK] CSV supprimes"

help:
	@echo ""
	@echo "Commandes:"
	@echo "  make setup           — Creer results/"
	@echo "  make port-forward    — Port-forward Prometheus :9090"
	@echo "  make scenario-4ues   — Baseline 4 UEs"
	@echo "  make scenario-10ues  — Scenario 10 UEs"
	@echo "  make scenario-20ues  — Scenario 20 UEs"
	@echo "  make all-scenarios   — Tous + comparaison"
	@echo "  make compare         — Comparer CSV existants"
	@echo "  make reset-ues       — Supprimer UEs 006+"
	@echo "  make stop-traffic    — Arreter ping"
	@echo "  make clean           — Supprimer CSV"
	@echo ""

scenario-mobilite:
	@echo "=== SCENARIO MOBILITE : croissance + cycles connexion/deconnexion ==="
	mkdir -p results
	python3 scripts/provision-ues.py --start 6 --count 16
	python3 scripts/metrics-collector.py --scenario mobilite --duration 600 --interval 5 \
		--output results/scenario-mobilite.csv --prometheus http://localhost:9090 &

	@echo ""
	@echo "[PHASE 1] Croissance progressive : 4 -> 20 UE"
	@for i in 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21; do \
		python3 scripts/deploy-ues.py --count 1 --start $$i --timeout 60 ; \
		sleep $$((6 + RANDOM % 8)) ; \
	done

	@echo ""
	@echo "[PHASE 2] Trafic stable sur 20 UE (60s)"
	python3 scripts/traffic-gen.py --ues 20 --duration 60 --pps 150 --size 1400

	@echo ""
	@echo "[PHASE 3] Deconnexion d'un groupe d'UE (014-021, 8 UE)"
	python3 scripts/deploy-ues.py --delete --start 14 --count 8
	@echo "[INFO] Observation a 12 UE pendant 60s..."
	python3 scripts/traffic-gen.py --ues 12 --duration 60 --pps 150 --size 1400

	@echo ""
	@echo "[PHASE 4] Reconnexion du meme groupe (014-021)"
	python3 scripts/provision-ues.py --start 14 --count 8
	python3 scripts/deploy-ues.py --count 8 --start 14 --timeout 120
	@echo "[INFO] Attente etablissement sessions (40s)..."
	sleep 40
	@echo "[INFO] Observation a 20 UE pendant 60s..."
	python3 scripts/traffic-gen.py --ues 20 --duration 60 --pps 150 --size 1400

	@echo ""
	@echo "[PHASE 5] Deconnexion finale - retour vers la charge de base"
	python3 scripts/deploy-ues.py --delete --start 6 --count 16
	@echo "[INFO] Observation finale a 4 UE pendant 90s (cooldown)..."
	python3 scripts/traffic-gen.py --ues 4 --duration 60 --pps 50 --size 800
	sleep 90

	wait
	@echo "[FIN] results/scenario-mobilite.csv"

scenario-mobilite:
	@echo "=== SCENARIO MOBILITE : croissance + cycles connexion/deconnexion ==="
	mkdir -p results
	python3 scripts/provision-ues.py --start 6 --count 16
	python3 scripts/metrics-collector.py --scenario mobilite --duration 600 --interval 5 \
		--output results/scenario-mobilite.csv --prometheus http://localhost:9090 &

	@echo ""
	@echo "[PHASE 1] Croissance progressive : 4 -> 20 UE"
	@for i in 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21; do \
		python3 scripts/deploy-ues.py --count 1 --start $$i --timeout 60 ; \
		sleep $$((6 + RANDOM % 8)) ; \
	done

	@echo ""
	@echo "[PHASE 2] Trafic stable sur 20 UE (60s)"
	python3 scripts/traffic-gen.py --ues 20 --duration 60 --pps 150 --size 1400

	@echo ""
	@echo "[PHASE 3] Deconnexion d'un groupe d'UE (014-021, 8 UE)"
	python3 scripts/deploy-ues.py --delete --start 14 --count 8
	@echo "[INFO] Observation a 12 UE pendant 60s..."
	python3 scripts/traffic-gen.py --ues 12 --duration 60 --pps 150 --size 1400

	@echo ""
	@echo "[PHASE 4] Reconnexion du meme groupe (014-021)"
	python3 scripts/provision-ues.py --start 14 --count 8
	python3 scripts/deploy-ues.py --count 8 --start 14 --timeout 120
	@echo "[INFO] Attente etablissement sessions (40s)..."
	sleep 40
	@echo "[INFO] Observation a 20 UE pendant 60s..."
	python3 scripts/traffic-gen.py --ues 20 --duration 60 --pps 150 --size 1400

	@echo ""
	@echo "[PHASE 5] Deconnexion finale - retour vers la charge de base"
	python3 scripts/deploy-ues.py --delete --start 6 --count 16
	@echo "[INFO] Observation finale a 4 UE pendant 90s (cooldown)..."
	python3 scripts/traffic-gen.py --ues 4 --duration 60 --pps 50 --size 800
	sleep 90

	wait
	@echo "[FIN] results/scenario-mobilite.csv"

scenario-vague-amortie:
	@echo "=== SCENARIO VAGUE AMORTIE (pics 54 -> 44 -> 30 -> 4) ==="
	mkdir -p results
	python3 scripts/metrics-collector.py --scenario vague_amortie --duration 900 --interval 5 \
		--output results/scenario-vague-amortie.csv --prometheus http://localhost:9090 &

	@echo "[1a] Connexion progressive 006->020 (15, une par une)"
	@for i in 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
		python3 scripts/deploy-ues.py --count 1 --start $$i --timeout 60 ; \
		sleep $$((5 + RANDOM % 5)) ; \
	done

	@echo "[1b] Connexion batch 021-055 (35) -> PIC 1 = 54 UE"
	python3 scripts/deploy-ues.py --count 35 --start 21 --timeout 240
	sleep 30
	python3 scripts/traffic-gen.py --ues 54 --duration 60 --pps 150 --size 1400

	@echo "[2] Deconnexion 016-055 (40) -> 14 UE"
	python3 scripts/deploy-ues.py --delete --start 16 --count 40
	python3 scripts/traffic-gen.py --ues 14 --duration 40 --pps 120 --size 1400

	@echo "[3] Connexion 016-045 (30) -> PIC 2 = 44 UE"
	python3 scripts/deploy-ues.py --count 30 --start 16 --timeout 210
	sleep 30
	python3 scripts/traffic-gen.py --ues 44 --duration 50 --pps 150 --size 1400

	@echo "[4] Deconnexion 011-045 (35) -> 9 UE"
	python3 scripts/deploy-ues.py --delete --start 11 --count 35
	python3 scripts/traffic-gen.py --ues 9 --duration 35 --pps 100 --size 1400

	@echo "[5] Connexion 011-031 (21) -> PIC 3 = 30 UE"
	python3 scripts/deploy-ues.py --count 21 --start 11 --timeout 150
	sleep 25
	python3 scripts/traffic-gen.py --ues 30 --duration 40 --pps 130 --size 1400

	@echo "[6] Deconnexion 006-031 (26) -> retour a 4 UE de base"
	python3 scripts/deploy-ues.py --delete --start 6 --count 26
	python3 scripts/traffic-gen.py --ues 4 --duration 60 --pps 50 --size 800
	sleep 100

	wait
	@echo "[FIN] results/scenario-vague-amortie.csv"
