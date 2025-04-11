import subprocess
import platform
import re

def trace_route(target, max_hops=None, no_resolve=False, ipv4=True, ipv6=False, timeout=None, source=None, gateway=None):
    """
    Performs a network route trace to the target and returns the route in a unified format.

    Args:
        target (str): The domain name or IP address to trace.
        max_hops (int, optional): Maximum number of hops. Defaults to None.
        no_resolve (bool, optional): Do not resolve IP addresses to hostnames. Defaults to False.
        ipv4 (bool, optional): Use IPv4. Defaults to False.
        ipv6 (bool, optional): Use IPv6. Defaults to False.
        timeout (float, optional): Timeout in seconds for each probe. Defaults to None.
        source (str, optional): Source address for outgoing packets. Defaults to None.
        gateway (list, optional): List of gateways for loose source routing. Defaults to None.

    Returns:
        list: A list of hops, each hop is a list containing [ip] or [ip, hostname].
    """
    os_name = platform.system().lower()
    command = []

    if os_name == 'windows':
        command.append('tracert')
        if max_hops is not None:
            command.extend(['/h', str(max_hops)])
        if no_resolve:
            command.append('/d')
        if ipv4:
            command.append('/4')
        if ipv6:
            command.append('/6')
        if timeout is not None:
            command.extend(['/w', str(int(timeout * 1000))])
        if source is not None:
            command.extend(['/S', source])
        if gateway is not None:
            command.extend(['/j'] + gateway)
        command.append(target)
    else:
        command.append('traceroute')
        if max_hops is not None:
            command.extend(['-m', str(max_hops)])
        if no_resolve:
            command.append('-n')
        if ipv4:
            command.append('-4')
        if ipv6:
            command.append('-6')
        if timeout is not None:
            command.extend(['-w', f"{timeout},3,10"])
        if source is not None:
            command.extend(['-s', source])
        if gateway is not None:
            command.extend(['-g', ','.join(gateway)])
        command.append(target)

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        output = result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed: {e.stderr}")

    hops = []
    if os_name == 'windows':
        for line in output.split('\n'):
            line = line.strip()
            hop_match = re.match(r'^\s*(\d+)\s+', line)
            if not hop_match:
                continue
            parts = line.split()
            current_index = 1
            entries_processed = 0

            # Process three timing entries (each can be "*" or "X ms")
            while entries_processed < 3 and current_index < len(parts):
                if parts[current_index] == '*':
                    current_index += 1
                    entries_processed += 1
                elif current_index + 1 < len(parts) and parts[current_index + 1].lower() == 'ms':
                    current_index += 2
                    entries_processed += 1
                else:
                    break  # Unexpected format, skip remaining

            if entries_processed < 3:
                continue  # Skip incomplete hop lines

            host_ip_part = ' '.join(parts[current_index:])
            ip = None
            hostname = None

            # Extract IP within brackets
            ip_match = re.search(r'\[(\d+\.\d+\.\d+\.\d+)\]$', host_ip_part)
            if ip_match:
                ip = ip_match.group(1)
                hostname = host_ip_part[:ip_match.start()].strip()
                # Clean hostname by removing residual timing parts (e.g., "ms")
                hostname = re.sub(r'\s*\d+ms\s*|\s*ms\s*', '', hostname, flags=re.IGNORECASE).strip()
                if not hostname:
                    hostname = None
            else:
                # Extract standalone IP
                ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)$', host_ip_part)
                if ip_match:
                    ip = ip_match.group(1)
                    hostname_part = host_ip_part[:ip_match.start()].strip()
                    hostname = re.sub(r'\s*\d+ms\s*|\s*ms\s*', '', hostname_part, flags=re.IGNORECASE).strip()
                    if not hostname or hostname == ip:
                        hostname = None

            if ip:
                if hostname:
                    hops.append([ip, hostname])
                else:
                    hops.append([ip])
            else:
                hops.append([None])  # Indicate unknown hop
    else:
        for line in output.split('\n'):
            line = line.strip()
            hop_match = re.match(r'^\s*(\d+)\s+', line)
            if not hop_match:
                continue
            ip = None
            hostname = None
            host_ip_match = re.search(r'([^\(\s]+)\s+\((\d+\.\d+\.\d+\.\d+)\)', line)
            if host_ip_match:
                hostname = host_ip_match.group(1)
                ip = host_ip_match.group(2)
                if hostname == ip:
                    hostname = None
            else:
                ip_match = re.search(r'\b(\d+\.\d+\.\d+\.\d+)\b', line)
                if ip_match:
                    ip = ip_match.group(1)
            if ip:
                if hostname:
                    hops.append([ip, hostname])
                else:
                    hops.append([ip])
            else:
                hops.append([None])

    return hops
