from pathlib import Path

ROOT = '/data/rd05-zapret'
BASE = Path(__file__).resolve().parents[1]
CRONTAB = '/etc/crontabs/root'
CRON_ENTRY = f'* * * * * /bin/sh {ROOT}/ensure.sh >/tmp/rd05-ensure.log 2>&1'
REQUIRED_COMMANDS = (
    'iptables', 'ip6tables', 'ip', 'awk', 'sed', 'readlink', 'md5sum',
    'ipset', 'dnsmasq', 'cmp', 'nslookup', 'curl', 'jsonfilter',
    'tar', 'chmod', 'cp', 'rm', 'mkdir', 'cat', 'test', 'du', 'df', 'sh', 'kill',
)
