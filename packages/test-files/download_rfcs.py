"""Download RFC documents from IETF for testing."""

import os
import urllib.request
import time

# RFCs to download - mix of popular/important ones with good content
# These are well-known, substantial documents
RFCS = [
    # Core Internet protocols
    791,   # IP
    792,   # ICMP
    793,   # TCP
    768,   # UDP
    826,   # ARP

    # HTTP
    2616,  # HTTP/1.1
    7230,  # HTTP/1.1 Message Syntax
    7231,  # HTTP/1.1 Semantics
    7540,  # HTTP/2

    # Security
    5246,  # TLS 1.2
    8446,  # TLS 1.3
    4301,  # IPsec
    5280,  # X.509 PKI
    6749,  # OAuth 2.0
    7519,  # JWT

    # DNS
    1034,  # DNS Concepts
    1035,  # DNS Implementation
    8484,  # DNS over HTTPS

    # Email
    5321,  # SMTP
    5322,  # Internet Message Format
    2045,  # MIME Part 1
    2046,  # MIME Part 2

    # Other important protocols
    2818,  # HTTP over TLS
    3986,  # URI Generic Syntax
    4648,  # Base Encodings
    7159,  # JSON
    8259,  # JSON (updated)

    # WebSocket
    6455,  # WebSocket

    # REST/API
    7807,  # Problem Details for HTTP APIs

    # Authentication
    7617,  # HTTP Basic Auth
    7616,  # HTTP Digest Auth

    # More protocols
    2131,  # DHCP
    3315,  # DHCPv6
    4862,  # IPv6 SLAAC
    8200,  # IPv6

    # FTP, SSH
    959,   # FTP
    4251,  # SSH Protocol
    4252,  # SSH Authentication
    4253,  # SSH Transport

    # LDAP
    4510,  # LDAP Technical Spec
    4511,  # LDAP Protocol

    # NTP
    5905,  # NTP v4

    # SIP/VoIP
    3261,  # SIP

    # Misc
    2119,  # Key words (MUST, SHALL, etc)
    3629,  # UTF-8
    5234,  # ABNF
    7693,  # BLAKE2 Hash

    # More for variety (to reach ~100)
    1939,  # POP3
    3501,  # IMAP
    4422,  # SASL
    5849,  # OAuth 1.0
    6750,  # OAuth Bearer Token
    7235,  # HTTP Authentication
    7236,  # HTTP Auth Scheme Registrations
    7525,  # TLS Recommendations
    8017,  # PKCS #1
    8032,  # EdDSA
    8152,  # COSE
    8174,  # RFC 2119 Keywords Update
    8288,  # Web Linking
    8392,  # CWT (CBOR Web Token)
    8414,  # OAuth Server Metadata
    8615,  # Well-Known URIs
    8725,  # JWT Best Practices
    9000,  # QUIC
    9001,  # QUIC TLS
    9110,  # HTTP Semantics
    9111,  # HTTP Caching
    9112,  # HTTP/1.1
    9113,  # HTTP/2
    9114,  # HTTP/3

    # Additional RFCs to reach 100
    854,   # Telnet
    855,   # Telnet Options
    1122,  # Host Requirements
    1123,  # Host Requirements (Applications)
    1321,  # MD5
    2104,  # HMAC
    2460,  # IPv6 (original)
    3168,  # ECN
    3339,  # Date and Time on Internet
    3550,  # RTP
    3711,  # SRTP
    4271,  # BGP-4
    4291,  # IPv6 Addressing
    4632,  # CIDR
    4880,  # OpenPGP
    5246,  # TLS 1.2
    5321,  # SMTP
    5652,  # CMS
    5869,  # HKDF
    6066,  # TLS Extensions
    6347,  # DTLS 1.2
    6570,  # URI Template
    6698,  # DANE/TLSA
    6797,  # HTTP Strict Transport Security
    6962,  # Certificate Transparency
    7230,  # HTTP/1.1 Message Syntax
    7468,  # Textual Encoding of PKIX
    8555,  # ACME (Let's Encrypt)
]

# Remove duplicates and take first 100
RFCS = list(dict.fromkeys(RFCS))[:100]

def download_rfc(rfc_num, output_dir):
    """Download a single RFC."""
    url = f"https://www.rfc-editor.org/rfc/rfc{rfc_num}.txt"
    filename = os.path.join(output_dir, f"rfc{rfc_num}.txt")

    if os.path.exists(filename):
        return True, "exists"

    try:
        urllib.request.urlretrieve(url, filename)
        return True, "downloaded"
    except Exception as e:
        return False, str(e)

def main():
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normal")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Downloading {len(RFCS)} RFC documents to: {output_dir}")
    print("=" * 60)

    success_count = 0
    for i, rfc_num in enumerate(RFCS, 1):
        success, status = download_rfc(rfc_num, output_dir)
        if success:
            success_count += 1
            print(f"[{i:3d}/{len(RFCS)}] RFC {rfc_num}: {status}")
        else:
            print(f"[{i:3d}/{len(RFCS)}] RFC {rfc_num}: FAILED - {status}")

        # Small delay to be polite to the server
        if status == "downloaded":
            time.sleep(0.5)

    print("=" * 60)
    print(f"Downloaded {success_count}/{len(RFCS)} RFCs")

    # Print stats
    total_size = sum(
        os.path.getsize(os.path.join(output_dir, f))
        for f in os.listdir(output_dir)
        if f.endswith('.txt')
    )
    file_count = len([f for f in os.listdir(output_dir) if f.endswith('.txt')])
    print(f"Total files: {file_count}")
    print(f"Total size: {total_size / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    main()
