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
	python3 $(SCRIPTS)/traffic-gen.py --ues 4 --duration $(DURATION) --pps 200 --size 1400 &
	python3 $(SCRIPTS)/metrics-collector.py --scenario 4ues --duration $(DURATION) --interval $(INTERVAL) --output $(RESULTS)/scenario-4ues.csv --prometheus $(PROMETHEUS)
	@wait
	@echo "[FIN] $(RESULTS)/scenario-4ues.csv"

scenario-10ues: setup check-prometheus
	@echo "=== SCENARIO 2 : 10 UEs ==="
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
	python3 $(SCRIPTS)/deploy-ues.py --count 16 --start 6 --timeout 300
	@echo "[INFO] Attente etablissement PDU sessions (60s)..."
	sleep 60
	python3 $(SCRIPTS)/traffic-gen.py --ues 20 --duration $(DURATION) --pps 200 --size 1400 &
	python3 $(SCRIPTS)/metrics-collector.py --scenario 20ues --duration $(DURATION) --interval $(INTERVAL) --output $(RESULTS)/scenario-20ues.csv --prometheus $(PROMETHEUS)
	@wait
	python3 $(SCRIPTS)/deploy-ues.py --delete --start 6 --count 16
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
