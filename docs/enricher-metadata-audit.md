# Enricher metadata audit — 2026-10-16

Audited all 49 registered built-in enrichers against their implementation, parameter
schemas and tool adapters. This is a source-code audit: no enrichments were launched
and provider availability, subscription plans and billing were not tested.

## Metadata contract

Each built-in class declares an immutable `EnricherMetadata` beside its input/output
types. The registry uses it for `description`, `providers`, `api_key_requirement`
and `api_key_notes`. These fields reach the administration GET/PATCH responses,
the regular enricher catalog, flow materials and input-type launch menus.

`providers` identifies named data services **or tool integrations**, including local
tools such as Maigret and ProjectDiscovery HTTPX. Naming a tool does not imply a
hosted API call. An empty list means no fixed named provider (local parsing, system
DNS, registry WHOIS or direct target-page requests); it does not mean no network
access. Descriptions distinguish these cases and list meaningful result limits.

API-key states describe the current Flowsint integration:

| Value | Meaning | Built-ins |
| --- | --- | ---: |
| `required` | The configured integration needs a key | 19 |
| `optional` | A key/token can be configured but is not mandatory in this implementation | 3 |
| `conditional` | The selected mode determines whether a key is needed | 1 |
| `not_required` | No provider API key is configured by this integration | 26 |
| `unknown` | No valid explicit declaration, used for legacy/custom templates | 0 |

These fields describe requirements, not whether a key is present in the current
user’s vault. They neither expose credentials nor enable unavailable tools.
Docker-based enrichers still require a working tool runner; the canonical local
stack currently leaves these execution capabilities disabled.

## Important implementation findings

- `ip_to_ports`: Naabu defaults to passive mode, which requires `PDCP_API_KEY`;
  active mode directly probes the target and does not require that key. A required
  mode selector is not itself an API-key requirement.
- `cidr_to_ips`, `domain_to_dns`: optional `PDCP_API_KEY`; `n8n_connector`: optional
  Bearer `auth_token`, with destination-specific authentication. Webhook URL is an
  ordinary required parameter, not an API key.
- `phone_to_device_hudsonrock`: currently sends the phone text to
  **search-by-username**, not a dedicated phone search. Its description states this.
- `domain_to_dummy`, `ip_to_dummy_domains`: synthetic test results, explicitly
  labelled as fabricated findings.
- `cryptowallet_to_transactions`: first 100 normal ETH transactions;
  `cryptowallet_to_nfts`: first page of up to 10,000 NFT transfers, not current
  ownership. Neither currently paginates the full history.
- `domain_to_tls`: currently emits Website probe results, not structured certificate
  records. `domain_to_root_domain` uses a small suffix heuristic, not the full PSL.
- French organization lookups use the public Recherche d’entreprises endpoint
  through SireneTool, not an authenticated INSEE API integration.
- Scamalytics configuration names retain the existing spelling
  `SCAMLYTICS_API_KEY`, `SCAMLYTICS_USERNAME`, `SCAMLYTICS_API_HOST`.
- Account/name/WHOIS matches are associations, not identity or ownership proofs.

The audit adds declarations only; it does not change scan logic, network requests,
parameter validation, vault lookup or graph-writing behavior.

## Complete inventory

The linked class-level declarations are the maintained source of truth. Keep this
snapshot synchronized when changing a provider, key requirement or scan behavior.

| Enricher / source | Provider or integration | API key | Description / notes |
| --- | --- | --- | --- |
| [asn_to_cidrs](../flowsint-enrichers/src/flowsint_enrichers/asn/to_cidrs.py) | ProjectDiscovery | `required` | Looks up CIDR network ranges associated with an autonomous system number using ProjectDiscovery ASNMAP and adds the results and their relationships to the investigation graph. Requires PDCP_API_KEY for the ASNMAP integration. |
| [cidr_to_ips](../flowsint-enrichers/src/flowsint_enrichers/cidr/to_ips.py) | ProjectDiscovery | `optional` | Expands a CIDR range into individual IP addresses using the ProjectDiscovery MAPCIDR Docker tool. This is address enumeration, not a check that the hosts are reachable. PDCP_API_KEY may be supplied to the tool but is not required by this enricher for CIDR expansion. |
| [cryptowallet_to_nfts](../flowsint-enrichers/src/flowsint_enrichers/crypto/to_nfts.py) | Etherscan | `required` | Queries Etherscan NFT transfer history for a cryptocurrency wallet and creates NFT records from the returned transfers. The current implementation requests the first page of up to 10,000 transfers; it does not establish current NFT ownership. Requires ETHERSCAN_API_KEY. ETHERSCAN_API_URL can override the default Etherscan API endpoint. |
| [cryptowallet_to_transactions](../flowsint-enrichers/src/flowsint_enrichers/crypto/to_transactions.py) | Etherscan | `required` | Fetches normal Ethereum transactions for a wallet from Etherscan and creates transaction and wallet relationships. The current implementation requests the first 100 transactions in ascending order, so the result is not a complete transaction history. Requires ETHERSCAN_API_KEY. ETHERSCAN_API_URL can override the default Etherscan API endpoint. |
| [domain_to_asn](../flowsint-enrichers/src/flowsint_enrichers/domain/to_asn.py) | ProjectDiscovery | `required` | Looks up autonomous systems associated with a domain using ProjectDiscovery ASNMAP and adds the results and their relationships to the investigation graph. Requires PDCP_API_KEY for the ASNMAP integration. |
| [domain_to_dehashed](../flowsint-enrichers/src/flowsint_enrichers/domain/to_dehashed.py) | DeHashed | `required` | Searches DeHashed breach data for the input domain. Converts matching identity fields, such as names, email addresses and usernames, into Individual records and links them to the input. Matches are reported associations, not independently verified identities. Requires DEHASHED_API_KEY. |
| [domain_to_dns](../flowsint-enrichers/src/flowsint_enrichers/domain/to_dns.py) | ProjectDiscovery | `optional` | Resolves a domain to IPv4 addresses and, when enabled, IPv6 addresses using the ProjectDiscovery DNSX Docker tool. Adds the resolved IP addresses and domain relationships to the graph. PDCP_API_KEY can optionally be passed to DNSX; ordinary DNS resolution does not require it in this enricher. |
| [domain_to_dummy](../flowsint-enrichers/src/flowsint_enrichers/domain/to_dummy_individuals.py) | — | `not_required` | Generates synthetic test data: a subdomain prefixed with sub. and a fabricated email address based on the input domain. These are fixtures for testing enrichment and graph updates, not discovered contacts or real DNS findings. |
| [domain_to_history](../flowsint-enrichers/src/flowsint_enrichers/domain/to_history.py) | Whoxy | `required` | Fetches historical WHOIS records for a domain from Whoxy. Extracts available ownership and contact information and creates related people, organizations, addresses and domain relationships. Requires WHOXY_API_KEY. |
| [domain_to_ip](../flowsint-enrichers/src/flowsint_enrichers/domain/to_ip.py) | — | `not_required` | Resolves a domain through the system DNS resolver using socket.gethostbyname. Returns one IPv4 address for each successfully resolved domain; it does not enumerate all DNS records or IPv6 addresses. |
| [domain_to_root_domain](../flowsint-enrichers/src/flowsint_enrichers/domain/to_root_domain.py) | — | `not_required` | Derives a root domain locally from a subdomain and adds a HAS_SUBDOMAIN relationship. Uses a small built-in list of common multi-part country suffixes and otherwise takes the last two labels; it does not use a complete Public Suffix List. |
| [domain_to_subdomains](../flowsint-enrichers/src/flowsint_enrichers/domain/to_subdomains.py) | ProjectDiscovery, crt.sh | `not_required` | Discovers subdomains using the Subfinder Docker tool, with public crt.sh certificate-transparency results as a fallback. Removes wildcard prefixes and excludes the root domain from subdomain results. No API key is configured by this enricher. Individual optional Subfinder data sources may have their own requirements outside this integration. |
| [domain_to_tls](../flowsint-enrichers/src/flowsint_enrichers/domain/to_ssl.py) | ProjectDiscovery | `not_required` | Probes a domain with the ProjectDiscovery HTTPX Docker tool using its TLS-probe option. The current enricher emits Website records with available URL, title, content type and HTTP status; it does not emit a structured TLS certificate record. |
| [domain_to_website](../flowsint-enrichers/src/flowsint_enrichers/domain/to_website.py) | — | `not_required` | Checks the input domain over HTTPS and falls back to HTTP. For a successful response below HTTP 400, creates a Website record with available page title and response information. Contacts the target website directly. |
| [domain_to_whois](../flowsint-enrichers/src/flowsint_enrichers/domain/to_whois.py) | — | `not_required` | Queries current domain WHOIS data through the python-whois library and creates a Whois record with available registrar, organization, location, email and registration dates. Availability and redaction depend on the relevant registry; no fixed commercial API provider is configured. |
| [domain_to_whois_history](../flowsint-enrichers/src/flowsint_enrichers/domain/to_whois_history.py) | WhoisXML API | `required` | Retrieves historical WHOIS records for a domain using the WhoisXML API WHOIS History service. Converts available historical registration and contact information into graph records. Requires WHOISXML_API_KEY. |
| [email_to_breaches](../flowsint-enrichers/src/flowsint_enrichers/email/to_leaks.py) | Have I Been Pwned | `required` | Queries Have I Been Pwned for breaches associated with an email address and creates breach records from returned names and metadata. It reports known breach exposure and does not retrieve account passwords. Requires HIBP_API_KEY. HIBP_API_URL can override the breached-account endpoint. |
| [email_to_device_hudsonrock](../flowsint-enrichers/src/flowsint_enrichers/email/to_hudsonrock.py) | Hudson Rock | `not_required` | Searches the public Hudson Rock Cavalier endpoint by email address for infostealer exposure. Creates Device records from available computer name, operating system, stealer family, IP and compromise-date information. Uses the public Hudson Rock Cavalier OSINT endpoint; no API key is configured by this enricher. |
| [email_to_domain](../flowsint-enrichers/src/flowsint_enrichers/email/to_domain.py) | — | `not_required` | Extracts the domain portion after @ from an email address and creates a Domain record linked to the email. This is local parsing and does not verify DNS or mailbox existence. |
| [email_to_domains](../flowsint-enrichers/src/flowsint_enrichers/email/to_domains.py) | Whoxy | `required` | Runs a Whoxy reverse-WHOIS search for the input email address, matching the registrant/contact email. Adds returned domains and available contact relationships. A matching record is an association from WHOIS data, not proof of current ownership. Requires WHOXY_API_KEY. |
| [email_to_gravatar](../flowsint-enrichers/src/flowsint_enrichers/email/to_gravatar.py) | Gravatar | `not_required` | Hashes the normalized email address and checks public Gravatar avatar and profile endpoints. Extracts an available avatar, display name, biography and location; an absent public profile produces no profile finding. Uses public Gravatar endpoints without a configured API key. |
| [email_to_intelligence](../flowsint-enrichers/src/flowsint_enrichers/email/to_dehashed.py) | DeHashed | `required` | Searches DeHashed breach data for the input email address. Converts matching identity fields, such as names, email addresses and usernames, into Individual records and links them to the input. Matches are reported associations, not independently verified identities. Requires DEHASHED_API_KEY. |
| [email_to_username](../flowsint-enrichers/src/flowsint_enrichers/email/to_username.py) | — | `not_required` | Takes the local part of an email address before @ and creates a Username candidate. This is a local inference and does not verify that an account with that username exists. |
| [individual_to_domains](../flowsint-enrichers/src/flowsint_enrichers/individual/to_domains.py) | Whoxy | `required` | Runs a Whoxy reverse-WHOIS search for the input person’s full name, matching the registrant/contact name. Adds returned domains and available contact relationships. A matching record is an association from WHOIS data, not proof of current ownership. Requires WHOXY_API_KEY. |
| [individual_to_organization](../flowsint-enrichers/src/flowsint_enrichers/individual/to_org.py) | Recherche d’entreprises (France) | `not_required` | Searches the French public company-search API by a person’s full name, with a limit of 25 results, and creates matching organizations and WORKS_FOR relationships. A name match alone does not independently verify employment or distinguish namesakes. Uses the public French Recherche d’entreprises API; no API key is configured. |
| [ip_to_asn](../flowsint-enrichers/src/flowsint_enrichers/ip/to_asn.py) | ProjectDiscovery | `required` | Looks up autonomous systems associated with an IP address using ProjectDiscovery ASNMAP and adds the results and their relationships to the investigation graph. Requires PDCP_API_KEY for the ASNMAP integration. |
| [ip_to_domain](../flowsint-enrichers/src/flowsint_enrichers/ip/to_domain.py) | crt.sh | `not_required` | Attempts a reverse-DNS PTR lookup for the IP address through the system resolver. If it fails, searches public crt.sh records, examines up to the first 15 records and selects the first available domain name. Certificate matches do not establish current DNS resolution. System reverse DNS and the public crt.sh fallback require no configured API key. |
| [ip_to_dummy_domains](../flowsint-enrichers/src/flowsint_enrichers/ip/to_dummy_domains.py) | — | `not_required` | Generates 20 fabricated domains per input IP address, with a one-second delay between results, to exercise streaming and graph updates. This is a synthetic test enricher and performs no real domain discovery. |
| [ip_to_fraudscore](../flowsint-enrichers/src/flowsint_enrichers/ip/to_fraudscore.py) | Scamalytics | `required` | Requests the Scamalytics fraud-risk assessment for an IP address and creates risk information from the returned score, risk level and proxy-related flags. The assessment reflects the provider’s data, not an independent determination of abuse. Requires SCAMLYTICS_API_KEY and SCAMLYTICS_USERNAME (these are the current configuration spellings). SCAMLYTICS_API_HOST optionally selects the account’s API node. |
| [ip_to_infos](../flowsint-enrichers/src/flowsint_enrichers/ip/to_infos.py) | ip-api.com | `not_required` | Queries the public ip-api.com JSON endpoint for an IP address and enriches the input with available latitude, longitude, country, city and ISP. IP geolocation is approximate. Uses the public endpoint without a configured API key. |
| [ip_to_intelligence](../flowsint-enrichers/src/flowsint_enrichers/ip/to_dehashed.py) | DeHashed | `required` | Searches DeHashed breach data for the input IP address. Converts matching identity fields, such as names, email addresses and usernames, into Individual records and links them to the input. Matches are reported associations, not independently verified identities. Requires DEHASHED_API_KEY. |
| [ip_to_ports](../flowsint-enrichers/src/flowsint_enrichers/ip/to_ports.py) | ProjectDiscovery | `conditional` | Finds open ports using the ProjectDiscovery Naabu Docker tool and creates Port records with available service and version information. Passive mode uses provider data; active mode directly probes the target IP. PDCP_API_KEY is required for passive mode, which is the default. Active mode does not require this key. The parameter is optional in the schema because the requirement depends on the selected mode. |
| [n8n_connector](../flowsint-enrichers/src/flowsint_enrichers/n8n/connector.py) | n8n | `optional` | Sends the input entities and configured payload to a user-specified n8n webhook so that an external workflow can process them. The actual enrichment and returned entity types depend on that workflow; no fixed data source is implied. The webhook URL is required. An optional auth_token is sent as a Bearer token when configured; authentication requirements depend on the destination webhook. |
| [org_to_asn](../flowsint-enrichers/src/flowsint_enrichers/organization/to_asn.py) | ProjectDiscovery | `required` | Looks up autonomous systems associated with an organization name using ProjectDiscovery ASNMAP and adds the results and their relationships to the investigation graph. Requires PDCP_API_KEY for the ASNMAP integration. |
| [org_to_domains](../flowsint-enrichers/src/flowsint_enrichers/organization/to_domains.py) | Whoxy | `required` | Runs a Whoxy reverse-WHOIS search for the input organization name, matching the company name. Adds returned domains and available contact relationships. A matching record is an association from WHOIS data, not proof of current ownership. Requires WHOXY_API_KEY. |
| [org_to_infos](../flowsint-enrichers/src/flowsint_enrichers/organization/to_infos.py) | Recherche d’entreprises (France) | `not_required` | Searches the French public company-search API by organization name and enriches company information such as SIREN/SIRET identifiers, address, activity and available leaders. Coverage is French businesses and name matches may be ambiguous. Uses the public French Recherche d’entreprises API; no API key is configured. |
| [phone_to_carrier](../flowsint-enrichers/src/flowsint_enrichers/phone/to_carrier.py) | Veriphone | `required` | Looks up a phone number using the Veriphone verification API and enriches it with available carrier, country and validity information. Requires VERIPHONE_API_KEY. |
| [phone_to_device_hudsonrock](../flowsint-enrichers/src/flowsint_enrichers/phone/to_hudsonrock.py) | Hudson Rock | `not_required` | Passes the phone-number text to the public Hudson Rock Cavalier search-by-username endpoint and creates Device records from any returned infostealer exposure. The current implementation does not use a dedicated phone-number search endpoint, so this is not a verified phone lookup. Uses the public Hudson Rock Cavalier OSINT endpoint; no API key is configured by this enricher. |
| [tech_detect](../flowsint-enrichers/src/flowsint_enrichers/website/to_technologies.py) | ProjectDiscovery | `not_required` | Probes the target website with the ProjectDiscovery HTTPX Docker tool and its Wappalyzer-based technology detection. Converts detected technology names and available versions into Technology records. |
| [username_to_dehashed](../flowsint-enrichers/src/flowsint_enrichers/social/to_dehashed.py) | DeHashed | `required` | Searches DeHashed breach data for the input username. Converts matching identity fields, such as names, email addresses and usernames, into Individual records and links them to the input. Matches are reported associations, not independently verified identities. Requires DEHASHED_API_KEY. |
| [username_to_device_hudsonrock](../flowsint-enrichers/src/flowsint_enrichers/social/to_hudsonrock.py) | Hudson Rock | `not_required` | Searches the public Hudson Rock Cavalier endpoint by username for infostealer exposure and creates Device records with available computer, operating-system, IP, stealer and compromise-date information. Username matches may refer to different people. Uses the public Hudson Rock Cavalier OSINT endpoint; no API key is configured by this enricher. |
| [username_to_socials_maigret](../flowsint-enrichers/src/flowsint_enrichers/social/to_maigret.py) | Maigret | `not_required` | Runs the local Maigret command-line tool to search public websites for the input username and converts its JSON report into social-account records and available profile details. A username match does not prove that accounts belong to the same person. No API key is configured by this integration. The local Maigret executable and its supported target sites must be available. |
| [username_to_socials_sherlock](../flowsint-enrichers/src/flowsint_enrichers/social/to_sherlock.py) | Sherlock | `not_required` | Runs the local Sherlock command-line tool to search public websites for the input username and converts reported profile URLs into SocialAccount records. A username match does not prove that accounts belong to the same person. No API key is configured by this integration. The local Sherlock executable and its supported target sites must be available. |
| [website_to_crawler](../flowsint-enrichers/src/flowsint_enrichers/website/to_crawler.py) | ReconCrawl | `not_required` | Crawls pages from the target website using ReconCrawl and extracts email addresses and phone numbers, adding contact relationships to the graph. The current crawl is limited to 500 pages and uses a one-second request delay. Uses a local crawling integration and contacts target pages directly; no provider API key is configured. |
| [website_to_domain](../flowsint-enrichers/src/flowsint_enrichers/website/to_domain.py) | — | `not_required` | Parses the hostname from a website URL, removes the port and a leading www. prefix, and creates the corresponding Domain record. This is local URL parsing and does not fetch the website. |
| [website_to_links](../flowsint-enrichers/src/flowsint_enrichers/website/to_links.py) | ReconSpread | `not_required` | Crawls the target website with ReconSpread, including links outside its domain, and adds discovered link and domain relationships to the graph. Results depend on reachable pages and crawl limits. Uses a local crawling integration and contacts target pages directly; no provider API key is configured. |
| [website_to_subdomains](../flowsint-enrichers/src/flowsint_enrichers/website/to_subdomain.py) | c99.nl | `required` | Calls the c99.nl Subdomain Finder API using the input website URL. Creates Website results for discovered subdomains with available IP and Cloudflare information. Requires C99_API_KEY. |
| [website_to_text](../flowsint-enrichers/src/flowsint_enrichers/website/to_text.py) | — | `not_required` | Fetches the target page with an HTTP request and extracts its text with BeautifulSoup into a Phrase record. This does not run browser JavaScript, so client-rendered content may be missing. |
| [website_to_webtrackers](../flowsint-enrichers/src/flowsint_enrichers/website/to_webtrackers.py) | ReconTrack | `not_required` | Fetches the target website with ReconTrack and extracts supported tracking identifiers. Creates WebTracker records with the tracker source and code and links them to the website. Uses a local extraction library and contacts the target website directly; no provider API key is configured. |

## Custom templates

Templates may declare the same public `metadata` block in their YAML/JSON. It is
validated by the shared model and survives template parsing/storage:

```yaml
metadata:
  description: Looks up public IP information from Example.
  providers: [Example]
  api_key_requirement: required
  api_key_notes: Requires EXAMPLE_API_KEY.
```

This block is public catalog information: store only descriptions and configuration
**names**, never credential values. Existing templates without a valid block retain
their stored description and receive `unknown`, rather than a guessed yes/no.
Metadata is never inferred from request URLs, headers, payloads or vault values.
Private template request configuration is not added to the administration DTO.

No database migration is required: built-ins declare metadata in code, and template
metadata is part of the existing JSON content column. SQL head remains
`f5a6b7c8d9e0`.

## Administration

One flat table shows Category, Provider, API key and visibility controls for all
enrichers without expanding sections. Click an enricher name to open its full
description, key notes, provider, category, kind and input/output details. Provider
names are included in text search. Missing template metadata displays Unknown.

Regression coverage checks the complete built-in inventory, metadata consistency
across registry/API views, conditional and optional keys, template compatibility,
private request-field isolation, dialogs, provider search and visibility controls.
