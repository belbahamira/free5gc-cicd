from prometheus_client import start_http_server, Gauge
import time

throughput = Gauge('free5gc_upf_throughput_bps', 'UPF N3 throughput in bytes per second')

def read_bytes():
    total = 0
    for stat in ['rx_bytes', 'tx_bytes']:
        try:
            with open('/sys/class/net/n3/statistics/' + stat) as f:
                total += int(f.read().strip())
        except:
            pass
    return total

start_http_server(8081)
print('Sidecar started', flush=True)
interval = 15
while True:
    b1 = read_bytes()
    time.sleep(interval)
    b2 = read_bytes()
    bps = max(0, (b2 - b1) / interval)
    throughput.set(bps)
    print('UPF throughput: ' + str(round(bps, 2)) + ' bytes/sec', flush=True)
