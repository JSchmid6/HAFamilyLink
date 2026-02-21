# Google Family Link � Home Assistant Integration

![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)
![Version](https://img.shields.io/badge/version-0.4.0-blue)
![HA min version](https://img.shields.io/badge/Home%20Assistant-2023.10%2B-brightgreen)

Control Google Family Link parental controls directly from Home Assistant �
including AI-driven automation via any conversation agent (Google Extended,
OpenAI, local LLMs).

> **Disclaimer:** This integration uses the unofficial, reverse-engineered
> Google Kids Management API. Use at your own risk. Google may change or
> restrict this API at any time. This may violate Google's Terms of Service.

---

## Features

- **Supervised children as HA devices** � one device per child, created automatically on first setup.
- **Switch entities** � one switch per child (future: per-device lock/unlock).
- **Real API calls** � uses the same internal REST API as the `families.google.com` web app (`kidsmanagement-pa.clients6.google.com`).
- **Secure, cookie-based authentication** � no password stored; session cookies are kept in the HA config entry.
- **7 LLM agent tools** � lets any HA conversation agent manage screen time and app restrictions in natural language (see [AI / LLM tools](#ai--llm-tools)).
- **Platform-adaptive authentication** � automated Playwright browser login on x86-64 / manylinux ARM; manual cookie paste on Alpine / HAOS ARM.
- **Re-authentication flow** � HA will prompt you to re-paste cookies when the session expires.

---

## Installation

### Via HACS (recommended)

1. In HA, go to **HACS ? Integrations ? ? ? Custom repositories**.
2. Add `https://github.com/noiwid/HAFamilyLink` as an **Integration**.
3. Install *Google Family Link*, then restart Home Assistant.
4. Go to **Settings ? Devices & Services ? Add Integration** and search for *Family Link*.

### Manual

Copy the `custom_components/familylink/` folder into your HA `custom_components/` directory and restart.

---

## Setup

### Step 1 � Basic settings

Enter an integration name and optional polling/timeout values.

### Step 2 � Authentication

Two paths, chosen automatically:

| Platform | Method |
|---|---|
| x86-64 / manylinux ARM | Playwright opens a Chromium window � log in normally, cookies are captured automatically. |
| Alpine / HAOS ARM (no Playwright) | Paste cookies manually (see below). |

#### How to export cookies manually

1. Install **[Cookie-Editor](https://cookie-editor.com/)** in Chrome/Firefox/Edge.
2. Open **[families.google.com](https://families.google.com)** and log in.
3. Click the extension icon ? **Export ? Export as JSON**.
4. Paste the JSON into the *Session cookies (JSON)* field in HA and click Submit.

> When your session expires, HA shows a **Re-authenticate** notification. Click it and repeat the cookie-export step � no need to remove the integration.

---

## Entities

After setup, each supervised child appears as a **Device** in HA with:

| Entity | Type | Description |
|---|---|---|
| `switch.{child_name}_supervision` | Switch | Supervision active indicator (always on) |
| `sensor.{child_name}_screen_time_today` | Sensor | Total screen time today in minutes |
| `number.{child_name}_{app}_daily_limit` | Number | Adjustable daily time limit (min) – one per limited app |

> The number entities appear automatically for apps that already have a time limit set in the Family Link app.

---

## AI / LLM Tools

When a compatible conversation agent is configured in HA (e.g. *Google Extended*, *OpenAI Conversation*, *Ollama*), the integration registers a **Family Link API** with 7 callable tools:

| Tool | Description |
|---|---|
| `GetChildren` | List supervised children with their IDs |
| `GetScreenTime` | Today's per-app usage in seconds for a child |
| `GetAppRestrictions` | Current limits, blocked apps, always-allowed apps |
| `SetAppLimit` | Set a daily time limit (minutes) for an app |
| `BlockApp` | Block an app completely |
| `AllowApp` | Mark an app as always allowed |
| `RemoveAppLimit` | Remove a previously set time limit |

**Example natural language commands:**

> *"How long has Emma been on YouTube today?"*
> *"Set Fortnite to 1 hour per day for Luca."*
> *"Block TikTok for all children."*

To enable, go to the conversation agent's **options** and select the *Family Link* API under *Home Assistant API*.

---

## Architecture

```
HA Entities / LLM Tools
        �
        ?
FamilyLinkDataUpdateCoordinator   (coordinator.py)
        �  polls every 60 s (configurable)
        ?
FamilyLinkClient                  (client/api.py)
        �  aiohttp + SAPISIDHASH auth
        ?
kidsmanagement-pa.clients6.google.com/kidsmanagement/v1
```

### Directory structure

```
custom_components/familylink/
+-- __init__.py          Integration entry point; registers LLM API
+-- manifest.json        Integration metadata
+-- const.py             Constants (URLs, API key, domain)
+-- config_flow.py       Setup wizard & re-auth flow
+-- coordinator.py       DataUpdateCoordinator + action methods
+-- switch.py            Switch platform (one switch per child)
+-- llm_api.py           7 LLM agent tools + API registration
+-- exceptions.py        Custom exception hierarchy
+-- strings.json         UI strings (English source)
+-- auth/
�   +-- browser.py       Playwright & manual cookie authentication
�   +-- session.py       Cookie loading, validation, expiry check
+-- client/
�   +-- api.py           HTTP client (kidsmanagement API)
�   +-- models.py        Data models
+-- translations/
�   +-- en.json          English UI translations
+-- utils/
    +-- __init__.py
```

---

## Security

- **No password stored** � only session cookies, kept in the HA config entry.
- **HTTPS only** � all communication with Google is over TLS.
- **SAPISID-based auth** � per-request SHA-1 token derived from cookie + timestamp; never replayed.
- **Isolated browser session** � Playwright runs in a sandboxed Chromium process during setup only.

---

## Known limitations

1. **Unofficial API** � Google can change or shut down the endpoints at any time.
2. **One account** � currently only one Google account (family) per HA instance.
3. **No realtime push** � state is polled every 60 s (configurable).
4. **ARM / HAOS** � Playwright is not available; manual cookie export required every few weeks.
5. **App name matching** � app titles must match exactly as shown in the Play Store (e.g. `"YouTube"`). Android package names (e.g. `"com.google.android.youtube"`) always work as a fallback.

---

## Development

```bash
git clone https://github.com/noiwid/HAFamilyLink.git
cd HAFamilyLink
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
pytest tests/
```

### Versioning (semantic)

| Change type | Part to bump |
|---|---|
| Bug fix / small correction | `PATCH` (e.g. `0.3.0 ? 0.3.1`) |
| New feature / new entity | `MINOR` (e.g. `0.3.0 ? 0.4.0`) |
| Breaking / incompatible change | `MAJOR` (e.g. `0.3.0 ? 1.0.0`) |

The authoritative version is `custom_components/familylink/manifest.json`.

---

## Roadmap

| Version | Planned |
|---|---|
| **0.3.0** | Real kidsmanagement API, 7 LLM tools, per-child devices |
| **0.4.0** *(current)* | `sensor` for daily screen time, `number` for per-app time limits, options flow |
| **0.5.0** | Multiple accounts / families |
| **1.0.0** | HACS default repository submission |

---

## Licence

MIT � see [LICENSE](LICENSE).
