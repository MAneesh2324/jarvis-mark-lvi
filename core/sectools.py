"""Ethical-hacking tools as local reference knowledge: what each is for, how it is typically run, where it
fits in an authorised test, and how a defender detects and stops it.

Reference only. JARVIS explains these; it never runs a scanner or exploitation tool. The command examples are
the documentation-level invocations found in each tool's own man page, shown so the user understands them —
to be used only against systems the user owns or has written permission to test. Written in our own words
(checked 2026-11-06); verify current flags against each tool's official docs.

Unauthorised scanning or access is illegal in most places (e.g. the US CFAA, the UK Computer Misuse Act,
India's IT Act s43/s66). Get permission in writing and stay inside its scope.
"""
from __future__ import annotations


# The phases of an authorised engagement (PTES / OWASP WSTG, in plain terms).
PHASES = [
    ('recon', 'Reconnaissance', 'Gather information from public sources without touching the target directly (OSINT): '
     'names, domains, emails, technologies, leaked data.'),
    ('scanning', 'Scanning & Enumeration', 'Actively map the target: live hosts, open ports, services, versions, '
     'shares, users. The first phase that reaches the target, so the first that needs authorisation.'),
    ('vuln', 'Vulnerability Analysis', 'Match what was found against known weaknesses and misconfigurations, and '
     'confirm which are real rather than false positives.'),
    ('web', 'Web Application Testing', 'Probe a web app for the OWASP-style flaws: injection, broken access control, '
     'authentication and session weaknesses, misconfiguration.'),
    ('exploit', 'Exploitation', 'Prove impact by safely using a confirmed weakness to gain access or data, only as far '
     'as the rules of engagement allow.'),
    ('password', 'Credential Attacks', 'Test password strength: online guessing against a live service, or offline '
     'cracking of hashes already obtained lawfully in the engagement.'),
    ('post', 'Post-Exploitation', 'After access: see what it exposes (privileges, pivoting, sensitive data) to show '
     'business impact. Never beyond the agreed scope.'),
    ('wireless', 'Wireless', 'Assess Wi-Fi: encryption, rogue access points, handshake capture — only on networks you '
     'are authorised to test.'),
    ('reporting', 'Reporting', 'The deliverable: each finding with evidence, risk, and how to fix it, written so the '
     'owner can act. The phase that makes the work useful.'),
]
_PHASE_NAMES = {k: name for k, name, _ in PHASES}

# Each tool: what it is, how it is typically invoked (documentation-level), the phase it serves, and — just as
# important here — how a defender spots and blocks it.
TOOLS = [
    {'name': 'Nmap', 'category': 'scanning', 'purpose': 'The standard network scanner: discovers live hosts, open '
     'ports, service versions and operating systems, and runs scripted checks (NSE).',
     'usage': ['nmap -sV -p- target            # all ports, identify service versions',
               'nmap -sC -sV target            # default safe scripts + versions',
               'nmap -A target                 # OS, versions, scripts, traceroute',
               'nmap --script vuln target      # known-vulnerability scripts'],
     'defend': 'Shows as many connections across ports from one source in a short time. Detect with IDS rules '
               '(Snort/Suricata) and firewall logs; slow it with rate limiting; reduce findings by closing unused '
               'ports and not leaking version banners.'},
    {'name': 'Masscan', 'category': 'scanning', 'purpose': 'An internet-scale port scanner — far faster than Nmap for '
     'sweeping large ranges for open ports, at the cost of detail.',
     'usage': ['masscan -p80,443 10.0.0.0/8 --rate 1000   # find web ports across a range'],
     'defend': 'Very high connection rates from one source; same detections as Nmap but louder. Rate-limit and alert '
               'on SYN floods at the perimeter.'},
    {'name': 'Wireshark', 'category': 'recon', 'purpose': 'A graphical packet analyser: captures and dissects network '
     'traffic to understand protocols and spot cleartext data. Passive — it only reads what reaches the interface.',
     'usage': ['(GUI) choose an interface, capture, then filter: http, dns, tcp.port == 443',
               'tshark -i en0 -f "port 80"     # the command-line version'],
     'defend': 'Passive capture is hard to detect on the wire. The defence is encryption everywhere (TLS), network '
               'segmentation and switch port security, so a sniffer sees little of value.'},
    {'name': 'tcpdump', 'category': 'recon', 'purpose': 'The command-line packet capturer, present on most Unix hosts; '
     'used to record traffic for analysis (often opened later in Wireshark).',
     'usage': ['tcpdump -i any -w capture.pcap port 80     # record to a file',
               'tcpdump -i en0 host 10.0.0.5               # traffic to/from one host'],
     'defend': 'Same as Wireshark: encrypt traffic and segment networks; watch for interfaces in promiscuous mode on '
               'your own hosts.'},
    {'name': 'theHarvester', 'category': 'recon', 'purpose': 'OSINT gathering: collects emails, subdomains, hosts and '
     'names for a domain from public search engines and data sources. No contact with the target.',
     'usage': ['theHarvester -d example.com -b all          # emails and hosts from public sources'],
     'defend': 'Reduce your public footprint: limit the detail in WHOIS, DNS and staff directories; use role '
               'addresses; monitor for your domains appearing in breach dumps.'},
    {'name': 'Recon-ng', 'category': 'recon', 'purpose': 'A modular OSINT framework (Metasploit-style menus) for '
     'automating reconnaissance across many public data sources.',
     'usage': ['(interactive) marketplace install ...; modules load recon/domains-hosts/...; run'],
     'defend': 'Same as other OSINT: minimise exposed data and monitor your external attack surface.'},
    {'name': 'WhatWeb', 'category': 'recon', 'purpose': 'Fingerprints a website: the server, CMS, frameworks, '
     'JavaScript libraries and versions behind it.',
     'usage': ['whatweb example.com            # identify the tech stack'],
     'defend': 'Suppress version banners and Server/X-Powered-By headers; keep components current so a fingerprint '
               'reveals nothing exploitable.'},
    {'name': 'enum4linux-ng', 'category': 'scanning', 'purpose': 'Enumerates Windows/Samba (SMB) systems: shares, '
     'users, groups and password policy over SMB/RPC.',
     'usage': ['enum4linux-ng -A target        # full SMB enumeration'],
     'defend': 'Disable SMBv1 and anonymous/null sessions; restrict RPC; alert on share and user enumeration in '
               'Windows security logs.'},
    {'name': 'Nessus', 'category': 'vuln', 'purpose': 'A commercial vulnerability scanner: checks hosts and services '
     'against a large database of known issues and misconfigurations, and ranks them.',
     'usage': ['(web UI) define a scan policy, add targets in scope, run, export the report'],
     'defend': 'Authenticated scanning is itself a blue-team tool — run your own and patch what it finds. Detect '
               'unexpected scans by their volume and signature; keep systems patched so results stay short.'},
    {'name': 'OpenVAS / Greenbone', 'category': 'vuln', 'purpose': 'The open-source vulnerability scanner, an '
     'alternative to Nessus with a community feed of checks.',
     'usage': ['(web UI) create a target and task, run, review the report'],
     'defend': 'As with Nessus: scan your own estate regularly and remediate; patch management shrinks the findings.'},
    {'name': 'Nuclei', 'category': 'vuln', 'purpose': 'A fast, template-driven scanner: runs community YAML templates '
     'for known CVEs, exposures and misconfigurations across many hosts.',
     'usage': ['nuclei -u https://example.com                # run all templates',
               'nuclei -l hosts.txt -t cves/                 # CVE templates over a host list'],
     'defend': 'Templates map to known CVEs — patching closes them. Detect with WAF/IDS signatures for the probe '
               'patterns; rate-limit automated requests.'},
    {'name': 'Burp Suite', 'category': 'web', 'purpose': 'The leading web-app testing platform: an intercepting proxy '
     'to view and modify requests, plus tools to fuzz, repeat and (in Pro) scan for web flaws.',
     'usage': ['(GUI) set the browser proxy to Burp; Proxy > Intercept to edit requests; Repeater to resend; '
               'Intruder to fuzz parameters'],
     'defend': 'Server-side validation and output encoding, strong access control checks, a WAF, and rate limiting. '
               'Anomalous parameter tampering shows in application logs.'},
    {'name': 'OWASP ZAP', 'category': 'web', 'purpose': 'A free, open-source web-app scanner and intercepting proxy — '
     'the open alternative to Burp, scriptable for CI pipelines.',
     'usage': ['(GUI) proxy the browser through ZAP; spider the site; run the active scan',
               'zap.sh -cmd -quickurl https://example.com -quickout report.html'],
     'defend': 'Same as Burp; ZAP in a CI pipeline is also a defensive practice — scan your own app before release.'},
    {'name': 'sqlmap', 'category': 'web', 'purpose': 'Automates finding and exploiting SQL injection (OWASP A05) in a '
     'given request, and can extract database contents to prove impact.',
     'usage': ['sqlmap -u "https://site/item?id=1" --batch        # test one parameter',
               'sqlmap -r request.txt --dbs                       # use a saved request, list databases'],
     'defend': 'Parameterised queries / ORM bindings remove the class entirely; least-privilege DB accounts limit '
               'impact; a WAF and DB query logging catch attempts.'},
    {'name': 'Nikto', 'category': 'web', 'purpose': 'A web-server scanner: checks for dangerous files, outdated '
     'server software and common misconfigurations.',
     'usage': ['nikto -h https://example.com                     # scan a web server'],
     'defend': 'Very noisy — thousands of requests for known paths; easy to catch in access logs and block by IP. '
               'Remove default files and keep the server patched.'},
    {'name': 'Gobuster / ffuf / dirb', 'category': 'web', 'purpose': 'Content discovery: brute-force hidden '
     'directories, files, subdomains and parameters using a wordlist.',
     'usage': ['gobuster dir -u https://example.com -w wordlist.txt   # hidden paths',
               'ffuf -u https://example.com/FUZZ -w wordlist.txt      # same idea, faster'],
     'defend': 'A flood of 404s for guessed paths — alert on high 404 rates per source and rate-limit; do not leave '
               'sensitive files outside access control.'},
    {'name': 'Metasploit Framework', 'category': 'exploit', 'purpose': 'The standard exploitation framework: a library '
     'of exploits and payloads with a console to configure and launch them, and to manage sessions after access.',
     'usage': ['(msfconsole) search <cve>; use <module>; set RHOSTS target; set payload ...; run'],
     'defend': 'Exploits target known CVEs — patching is the primary defence. EDR detects common payloads and '
               'Meterpreter behaviour; network segmentation limits what a foothold can reach.'},
    {'name': 'Hydra', 'category': 'password', 'purpose': 'Online password guessing against a live service (SSH, FTP, '
     'HTTP forms and more) using username and password lists.',
     'usage': ['hydra -l admin -P wordlist.txt ssh://target        # guess an SSH password'],
     'defend': 'Account lockout / exponential backoff, rate limiting, MFA, and alerting on repeated auth failures. '
               'MFA defeats guessing even with the right password.'},
    {'name': 'John the Ripper', 'category': 'password', 'purpose': 'Offline password cracking: recovers passwords from '
     'hashes obtained lawfully during the test, to measure password strength.',
     'usage': ['john --wordlist=rockyou.txt hashes.txt           # dictionary attack',
               'john --show hashes.txt                           # reveal cracked ones'],
     'defend': 'Strong, unique passwords and slow salted hashing (Argon2id, bcrypt, scrypt) make offline cracking '
               'infeasible; protect the hash store so it is never obtained.'},
    {'name': 'Hashcat', 'category': 'password', 'purpose': 'GPU-accelerated offline hash cracking — the fastest option '
     'for large hash lists, with dictionary, rule and mask attacks.',
     'usage': ['hashcat -m 0 -a 0 hashes.txt rockyou.txt         # MD5 dictionary attack',
               'hashcat -m 1000 -a 3 hashes.txt ?a?a?a?a?a?a     # NTLM mask (brute) attack'],
     'defend': 'Same as John: modern slow hashing with salts, long passphrases, and keeping the hash store out of '
               'reach. Reject breached passwords at signup.'},
    {'name': 'Aircrack-ng', 'category': 'wireless', 'purpose': 'A Wi-Fi assessment suite: captures traffic, records '
     'the WPA handshake and tests its passphrase offline.',
     'usage': ['(authorised lab) airmon-ng start wlan0; airodump-ng wlan0mon; aircrack-ng -w wordlist capture.cap'],
     'defend': 'WPA3 or a long random WPA2 passphrase, 802.1X/enterprise auth, and wireless IDS to spot deauth '
               'floods and rogue access points.'},
    {'name': 'Responder', 'category': 'post', 'purpose': 'On a local network, answers LLMNR/NBT-NS/mDNS name requests '
     'to capture Windows authentication hashes — a classic internal-pentest technique.',
     'usage': ['(authorised internal test) responder -I eth0           # listen and capture'],
     'defend': 'Disable LLMNR and NBT-NS via Group Policy, enable SMB signing, and segment the network. Detect with '
               'honeypot name lookups and monitoring for rogue responders.'},
    {'name': 'BloodHound', 'category': 'post', 'purpose': 'Maps Active Directory relationships to reveal attack paths '
     'to Domain Admin. A collector gathers AD data; the GUI graphs the shortest paths.',
     'usage': ['(collector) SharpHound; then import the data into the BloodHound GUI and run path queries'],
     'defend': 'BloodHound is also a blue-team tool — run it to find and cut your own attack paths: tier admin '
               'accounts, remove excess rights, and monitor for mass AD enumeration.'},
    {'name': 'Netcat / Ncat', 'category': 'post', 'purpose': 'The "network Swiss army knife": opens, reads and writes '
     'raw TCP/UDP connections — used for banner grabbing, file transfer and simple listeners.',
     'usage': ['nc -lvnp 4444                 # listen on a port',
               'nc target 80                  # connect and talk to a service'],
     'defend': 'Egress filtering and allow-listed outbound connections stop reverse shells; EDR flags unusual '
               'listeners and outbound connections from servers.'},
]

_BY = {t['name'].split(' /')[0].lower(): t for t in TOOLS}

# Legal practice grounds — where to use all of the above without breaking the law.
LABS = [
    {'name': 'PortSwigger Web Security Academy', 'what': 'Free, guided labs for every web vulnerability class, from '
     'the makers of Burp. The best place to learn web testing.', 'url': 'https://portswigger.net/web-security'},
    {'name': 'TryHackMe', 'what': 'Guided, beginner-friendly rooms with in-browser machines; learn a tool or technique '
     'step by step.', 'url': 'https://tryhackme.com'},
    {'name': 'Hack The Box', 'what': 'Vulnerable machines and challenges from easy to hard; less hand-holding, closer '
     'to a real engagement.', 'url': 'https://www.hackthebox.com'},
    {'name': 'OWASP Juice Shop', 'what': 'A deliberately insecure modern web app you run yourself — practise the whole '
     'OWASP Top 10 locally.', 'url': 'https://owasp.org/www-project-juice-shop/'},
    {'name': 'DVWA', 'what': 'Damn Vulnerable Web Application: a classic PHP/MySQL target with adjustable difficulty, '
     'run in a local container.', 'url': 'https://github.com/digininja/DVWA'},
    {'name': 'VulnHub', 'what': 'Downloadable vulnerable VMs to practise full host compromise in an isolated lab.',
     'url': 'https://www.vulnhub.com'},
    {'name': 'Metasploitable', 'what': 'An intentionally vulnerable Linux VM, the standard target for learning '
     'Metasploit and scanning.', 'url': 'https://sourceforge.net/projects/metasploitable/'},
]

HOME_LAB = ('Build an isolated lab before using any of these tools: run the attacker box (e.g. Kali or Parrot) and the '
            'vulnerable targets as VMs on a host-only / internal network with no route to the internet or your home '
            'LAN, snapshot clean states, and never point a tool at a system you do not own or have written permission '
            'to test.')


def find(query: str):
    """A tool by name (or close substring), or None."""
    q = str(query or '').strip().lower()
    if not q:
        return None
    if q in _BY:
        return _BY[q]
    for key, tool in _BY.items():
        if q in key or key in q or q in tool['name'].lower():
            return tool
    aliases = {'burpsuite': 'burp suite', 'zap': 'owasp zap', 'msf': 'metasploit framework',
               'metasploit': 'metasploit framework', 'jtr': 'john the ripper', 'john': 'john the ripper',
               'aircrack': 'aircrack-ng', 'nc': 'netcat', 'ncat': 'netcat', 'dirb': 'gobuster / ffuf / dirb',
               'ffuf': 'gobuster / ffuf / dirb', 'enum4linux': 'enum4linux-ng'}
    for a, name in aliases.items():
        if a in q:
            return _BY.get(name.split(' /')[0])
    return None


def in_phase(phase: str) -> list:
    p = str(phase or '').strip().lower()
    key = next((k for k, name, _ in PHASES if k == p or name.lower() == p or p in name.lower()), None)
    return [t for t in TOOLS if t['category'] == key] if key else []


def phase_label(key: str) -> str:
    return _PHASE_NAMES.get(key, key)
